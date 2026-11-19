#!/usr/bin/env python3
"""
scripts/benchmark.py
--------------------------------------------------------------------------------
Compara PostgreSQL e Cassandra:

1. Leitura: cada consulta de relational/queries.sql e cassandra/queries.cql
   (1 aquecimento + média de N execuções, em ms).
2. Escrita: grava --ingest avaliações novas, uma a uma, com --procs processos
   clientes e --workers escritas simultâneas por processo, nos dois bancos
   (avaliações por segundo). Um único processo Python limita o driver do
   Cassandra a ~6 mil operações/s, por isso o padrão são 2 processos.
     - PostgreSQL: 1 INSERT em ratings (índices e chaves estrangeiras verificadas).
     - Cassandra: 2 INSERT (ratings_by_user e ratings_by_movie) + 1 UPDATE de
       contador (movie_stats) por avaliação, como na carga.
   As avaliações de teste usam usuários novos e são apagadas no final.

Grava a tabela em docs/resultados_benchmark.md.
--------------------------------------------------------------------------------
"""

import argparse
import multiprocessing
import platform
import random
import statistics
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta

from cassandra.concurrent import execute_concurrent_with_args

from common import ROOT, connect, connect_cassandra, load_queries
from test_cassandra_queries import statements

TEST_USER_BASE = 10_000_000  # ids de usuário de teste, fora da faixa do MovieLens


def timed(fn, runs):
    fn()  # aquecimento
    ts = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.mean(ts)


def fmt(ms):
    return f"{ms:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def bench_reads(pg, cs, runs):
    sql = {q["name"]: q for q in load_queries(ROOT / "relational" / "queries.sql")}
    cql = {q["name"]: q for q in load_queries(ROOT / "cassandra" / "queries.cql")}
    cur = pg.cursor()
    rows = []
    for name, q in sql.items():
        stmts = [cs.prepare(s) for s in statements(cql[name]["text"])]
        t_pg = timed(lambda: (cur.execute(q["text"]), cur.fetchall()), runs)
        t_cs = timed(lambda: [list(cs.execute(s)) for s in stmts], runs)
        print(f"[*] {q['titulo']}\n    PostgreSQL {fmt(t_pg)} ms | Cassandra {fmt(t_cs)} ms")
        rows.append((q["titulo"], t_pg, t_cs))
    cur.close()
    return rows


def sample_ratings(pg, n):
    cur = pg.cursor()
    cur.execute("SELECT movie_id FROM movies")
    movies = [r[0] for r in cur.fetchall()]
    cur.close()
    rnd = random.Random(42)
    base = datetime(2016, 1, 1)
    out = []
    for i in range(0, n, 50):  # 50 avaliações por usuário de teste, cada uma de um filme diferente
        for j, m in enumerate(rnd.sample(movies, min(50, n - i))):
            out.append((TEST_USER_BASE + i // 50, m, rnd.choice([0.5 * k for k in range(1, 11)]),
                        base + timedelta(seconds=i + j)))
    return out


def _pg_process(part, workers):
    """Um processo cliente: `workers` threads, cada uma com sua conexão, gravando uma avaliação por vez."""
    chunks = [part[i::workers] for i in range(workers)]
    errors = []

    def worker(chunk):
        try:
            conn = connect()
            conn.autocommit = True
            with conn.cursor() as cur:
                for u, m, r, t in chunk:
                    cur.execute("INSERT INTO ratings (user_id, movie_id, rating, rated_at) VALUES (%s, %s, %s, %s)",
                                (u, m, r, t))
            conn.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(c,)) for c in chunks]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return errors


def _cs_process(part, workers):
    """Um processo cliente: driver do Cassandra com `workers` escritas em andamento."""
    from cassandra.concurrent import execute_concurrent
    cluster, cs = connect_cassandra()
    by_user = cs.prepare("INSERT INTO movielens.ratings_by_user (user_id, rated_at, movie_id, rating) VALUES (?, ?, ?, ?)")
    by_movie = cs.prepare("INSERT INTO movielens.ratings_by_movie (movie_id, rated_at, user_id, rating) VALUES (?, ?, ?, ?)")
    stats = cs.prepare("UPDATE movielens.movie_stats SET half_stars_sum = half_stars_sum + ?, "
                       "rating_count = rating_count + 1 WHERE movie_id = ?")
    ops = []
    for u, m, r, t in part:
        ops += [(by_user, (u, t, m, r)), (by_movie, (m, t, u, r)), (stats, (int(r * 2), m))]
    try:
        for ok, res in execute_concurrent(cs, ops, concurrency=workers, raise_on_first_error=True):
            pass
        return []
    except Exception as exc:  # noqa: BLE001
        return [repr(exc)]
    finally:
        cluster.shutdown()


def _run_processes(target, ratings, procs, workers):
    """Divide as avaliações entre `procs` processos clientes e mede o tempo total."""
    parts = [ratings[i::procs] for i in range(procs)]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(procs, mp_context=multiprocessing.get_context("spawn")) as ex:
        errors = sum(ex.map(target, parts, [workers] * procs), [])
    elapsed = time.perf_counter() - t0
    return elapsed, errors


def ingest_pg(ratings, procs, workers):
    users = sorted({r[0] for r in ratings})
    with connect() as conn, conn.cursor() as cur:
        cur.executemany("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", [(u,) for u in users])
    elapsed, errors = _run_processes(_pg_process, ratings, procs, workers)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ratings WHERE user_id >= %s", (TEST_USER_BASE,))
        cur.execute("DELETE FROM users WHERE user_id >= %s", (TEST_USER_BASE,))
    if errors:
        raise RuntimeError(f"{len(errors)} falhas na escrita do PostgreSQL: {errors[0]}")
    return len(ratings) / elapsed


def ingest_cassandra(cs, ratings, procs, workers):
    elapsed, errors = _run_processes(_cs_process, ratings, procs, workers)
    # limpeza: remove as avaliações de teste e desfaz os contadores
    del_user = cs.prepare("DELETE FROM movielens.ratings_by_user WHERE user_id = ?")
    del_movie = cs.prepare("DELETE FROM movielens.ratings_by_movie WHERE movie_id = ? AND rated_at = ? AND user_id = ?")
    undo = cs.prepare("UPDATE movielens.movie_stats SET half_stars_sum = half_stars_sum - ?, "
                      "rating_count = rating_count - 1 WHERE movie_id = ?")
    for stmt, args in ((del_user, [(u,) for u in sorted({r[0] for r in ratings})]),
                       (del_movie, [(m, t, u) for u, m, r, t in ratings]),
                       (undo, [(int(r * 2), m) for u, m, r, t in ratings])):
        execute_concurrent_with_args(cs, stmt, args, concurrency=64, raise_on_first_error=True)
    # filmes que não tinham avaliações ficaram com contadores zerados: remove essas linhas
    sel = cs.prepare("SELECT half_stars_sum, rating_count FROM movielens.movie_stats WHERE movie_id = ?")
    dele = cs.prepare("DELETE FROM movielens.movie_stats WHERE movie_id = ?")
    zeros = [m for m in sorted({r[1] for r in ratings})
             if (row := cs.execute(sel, (m,)).one()) and row[0] == 0 and row[1] == 0]
    execute_concurrent_with_args(cs, dele, [(m,) for m in zeros], concurrency=64, raise_on_first_error=True)
    if errors:
        raise RuntimeError(f"{len(errors)} falhas na escrita do Cassandra: {errors[0]}")
    return len(ratings) / elapsed


def main():
    p = argparse.ArgumentParser(description="Benchmark PostgreSQL vs. Cassandra")
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--ingest", type=int, default=100_000, help="Avaliações gravadas no teste de escrita (0 pula).")
    p.add_argument("--procs", type=int, default=2, help="Processos clientes no teste de escrita (um só limita o Python).")
    p.add_argument("--workers", default="16", help="Escritas simultâneas por processo; vários níveis separados por vírgula.")
    p.add_argument("--skip-reads", action="store_true", help="Mede só a escrita.")
    p.add_argument("--out", default=str(ROOT / "docs" / "resultados_benchmark.md"))
    args = p.parse_args()

    pg = connect()
    pg.autocommit = True
    cluster, cs = connect_cassandra()
    cur = pg.cursor()
    cur.execute("SELECT COUNT(*) FROM ratings")
    n_ratings = cur.fetchone()[0]
    cur.close()

    reads = [] if args.skip_reads else bench_reads(pg, cs, args.runs)
    writes = []
    if args.ingest:
        ratings = sample_ratings(pg, args.ingest)
        for w in (int(x) for x in args.workers.split(",")):
            print(f"[*] Escrita: {args.ingest:,} avaliações, {args.procs} processos x {w} simultâneas")
            w_pg = ingest_pg(ratings, args.procs, w)
            print(f"    PostgreSQL {w_pg:,.0f} avaliações/s")
            w_cs = ingest_cassandra(cs, ratings, args.procs, w)
            print(f"    Cassandra  {w_cs:,.0f} avaliações/s")
            writes.append((f"{args.procs} × {w}", w_pg, w_cs))
    pg.close()
    cluster.shutdown()

    def winner(a, b, menor_melhor=True):
        if max(a, b) <= 1.1 * min(a, b):
            return "empate"
        return ("PostgreSQL" if a < b else "Cassandra") if menor_melhor else ("PostgreSQL" if a > b else "Cassandra")

    lines = [
        "# Resultados do Benchmark: PostgreSQL vs. Cassandra",
        "",
        f"- Data: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Máquina: {platform.system()} {platform.machine()}, Python {platform.python_version()}",
        f"- Avaliações carregadas: {n_ratings:,}".replace(",", "."),
        f"- Leitura: 1 aquecimento + média de {args.runs} execuções (ms).",
        "",
        "| Consulta | PostgreSQL (ms) | Cassandra (ms) | Mais rápido |",
        "| :--- | ---: | ---: | :---: |",
    ]
    lines += [f"| {t} | {fmt(a)} | {fmt(b)} | {winner(a, b)} |" for t, a, b in reads]
    if writes:
        lines += [
            "",
            f"## Escrita: {args.ingest:,}".replace(",", ".") + " avaliações novas, gravadas uma a uma",
            "",
            "| Processos × escritas simultâneas | PostgreSQL (avaliações/s) | Cassandra (avaliações/s) | Mais rápido |",
            "| ---: | ---: | ---: | :---: |",
        ]
        lines += [f"| {w} | {a:,.0f} | {b:,.0f} | {winner(a, b, False)} |".replace(",", ".") for w, a, b in writes]
        lines += [
            "",
            "No Cassandra cada avaliação são 3 escritas (2 tabelas + contador); no PostgreSQL, 1 INSERT "
            "com verificação de chaves estrangeiras e atualização de 3 índices.",
        ]
    lines.append("")
    open(args.out, "w", encoding="utf-8").write("\n".join(lines))
    print(f"\n[+] Tabela gravada em {args.out}")


if __name__ == "__main__":
    main()
