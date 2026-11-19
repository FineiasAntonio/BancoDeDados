#!/usr/bin/env python3
"""
scripts/benchmark.py
--------------------------------------------------------------------------------
Compara PostgreSQL e Cassandra:

1. Leitura: cada consulta de relational/queries.sql e cassandra/queries.cql
   (1 aquecimento + média de N execuções, em ms).
2. Escrita: grava --ingest avaliações novas, uma a uma, com --workers escritas
   simultâneas nos dois bancos (avaliações por segundo).
     - PostgreSQL: 1 INSERT em ratings (índices e chaves estrangeiras verificadas).
     - Cassandra: 2 INSERT (ratings_by_user e ratings_by_movie) + 1 UPDATE de
       contador (movie_stats) por avaliação, como na carga.
   As avaliações de teste usam usuários novos e são apagadas no final.

Grava a tabela em docs/resultados_benchmark.md.
--------------------------------------------------------------------------------
"""

import argparse
import platform
import random
import statistics
import threading
import time
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
    return [(TEST_USER_BASE + i // 50, rnd.choice(movies), rnd.choice([0.5 * k for k in range(1, 11)]),
             base + timedelta(seconds=i)) for i in range(n)]


def ingest_pg(pg_factory, ratings, workers):
    users = sorted({r[0] for r in ratings})
    with pg_factory() as conn, conn.cursor() as cur:
        cur.executemany("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", [(u,) for u in users])
    parts = [ratings[i::workers] for i in range(workers)]

    def worker(part):
        conn = pg_factory()
        conn.autocommit = True
        with conn.cursor() as cur:
            for u, m, r, t in part:
                cur.execute("INSERT INTO ratings (user_id, movie_id, rating, rated_at) VALUES (%s, %s, %s, %s)",
                            (u, m, r, t))
        conn.close()

    threads = [threading.Thread(target=worker, args=(p,)) for p in parts]
    t0 = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    elapsed = time.perf_counter() - t0
    with pg_factory() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ratings WHERE user_id >= %s", (TEST_USER_BASE,))
        cur.execute("DELETE FROM users WHERE user_id >= %s", (TEST_USER_BASE,))
    return len(ratings) / elapsed


def ingest_cassandra(cs, ratings, workers):
    by_user = cs.prepare("INSERT INTO movielens.ratings_by_user (user_id, rated_at, movie_id, rating) VALUES (?, ?, ?, ?)")
    by_movie = cs.prepare("INSERT INTO movielens.ratings_by_movie (movie_id, rated_at, user_id, rating) VALUES (?, ?, ?, ?)")
    stats = cs.prepare("UPDATE movielens.movie_stats SET half_stars_sum = half_stars_sum + ?, "
                       "rating_count = rating_count + 1 WHERE movie_id = ?")
    ops = []
    for u, m, r, t in ratings:
        ops += [(by_user, (u, t, m, r)), (by_movie, (m, t, u, r)), (stats, (int(r * 2), m))]
    t0 = time.perf_counter()
    from cassandra.concurrent import execute_concurrent
    for ok, res in execute_concurrent(cs, ops, concurrency=workers, raise_on_first_error=True):
        pass
    elapsed = time.perf_counter() - t0
    # limpeza: remove as avaliações de teste e desfaz os contadores
    del_user = cs.prepare("DELETE FROM movielens.ratings_by_user WHERE user_id = ?")
    del_movie = cs.prepare("DELETE FROM movielens.ratings_by_movie WHERE movie_id = ? AND rated_at = ? AND user_id = ?")
    undo = cs.prepare("UPDATE movielens.movie_stats SET half_stars_sum = half_stars_sum - ?, "
                      "rating_count = rating_count - 1 WHERE movie_id = ?")
    execute_concurrent_with_args(cs, del_user, [(u,) for u in sorted({r[0] for r in ratings})], concurrency=64)
    execute_concurrent_with_args(cs, del_movie, [(m, t, u) for u, m, r, t in ratings], concurrency=64)
    execute_concurrent_with_args(cs, undo, [(int(r * 2), m) for u, m, r, t in ratings], concurrency=64)
    return len(ratings) / elapsed


def main():
    p = argparse.ArgumentParser(description="Benchmark PostgreSQL vs. Cassandra")
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--ingest", type=int, default=100_000, help="Avaliações gravadas no teste de escrita (0 pula).")
    p.add_argument("--workers", type=int, default=16, help="Escritas simultâneas no teste de escrita.")
    p.add_argument("--out", default=str(ROOT / "docs" / "resultados_benchmark.md"))
    args = p.parse_args()

    pg = connect()
    pg.autocommit = True
    cluster, cs = connect_cassandra()
    cur = pg.cursor()
    cur.execute("SELECT COUNT(*) FROM ratings")
    n_ratings = cur.fetchone()[0]
    cur.close()

    reads = bench_reads(pg, cs, args.runs)
    w_pg = w_cs = None
    if args.ingest:
        ratings = sample_ratings(pg, args.ingest)
        print(f"[*] Escrita: {args.ingest:,} avaliações, {args.workers} simultâneas")
        w_pg = ingest_pg(connect, ratings, args.workers)
        print(f"    PostgreSQL {w_pg:,.0f} avaliações/s")
        w_cs = ingest_cassandra(cs, ratings, args.workers)
        print(f"    Cassandra  {w_cs:,.0f} avaliações/s")
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
    if w_pg:
        lines += [
            "",
            f"## Escrita: {args.ingest:,} avaliações novas, {args.workers} simultâneas".replace(",", "."),
            "",
            "| | PostgreSQL | Cassandra | Mais rápido |",
            "| :--- | ---: | ---: | :---: |",
            f"| Avaliações por segundo | {w_pg:,.0f} | {w_cs:,.0f} | {winner(w_pg, w_cs, False)} |".replace(",", "."),
            "",
            "No Cassandra cada avaliação são 3 escritas (2 tabelas + contador); no PostgreSQL, 1 INSERT "
            "com verificação de chaves estrangeiras e atualização de 3 índices.",
        ]
    lines.append("")
    open(args.out, "w", encoding="utf-8").write("\n".join(lines))
    print(f"\n[+] Tabela gravada em {args.out}")


if __name__ == "__main__":
    main()
