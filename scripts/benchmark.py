#!/usr/bin/env python3
"""
scripts/benchmark.py
--------------------------------------------------------------------------------
Mede o tempo de cada consulta nos dois bancos (PostgreSQL e Neo4j).

Para cada consulta: 1 execução de aquecimento (descartada) + N execuções medidas.
Reporta a mediana em milissegundos e grava a tabela em docs/resultados_benchmark.md.
Consultas que passam do timeout aparecem como "> Ns".
--------------------------------------------------------------------------------
"""

import argparse
import platform
import statistics
import time
from datetime import datetime

import psycopg2

from common import ROOT, connect, connect_neo4j, load_queries


def measure(fn, runs):
    fn()  # aquecimento: cache de páginas e planos
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def fmt(ms):
    if isinstance(ms, str):
        return ms
    return f"{ms:,.1f}" if ms < 1000 else f"{ms:,.0f}"


def main():
    p = argparse.ArgumentParser(description="Benchmark PostgreSQL vs. Neo4j")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--timeout", type=int, default=60, help="Timeout por execução, em segundos.")
    p.add_argument("--out", default=str(ROOT / "docs" / "resultados_benchmark.md"))
    args = p.parse_args()

    sql = {q["name"]: q for q in load_queries(ROOT / "relational" / "queries.sql")}
    cypher = {q["name"]: q for q in load_queries(ROOT / "neo4j" / "queries.cypher")}

    conn = connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"SET statement_timeout = '{args.timeout}s'")
    cur.execute("SELECT COUNT(*) FROM ratings")
    n_ratings = cur.fetchone()[0]

    driver = connect_neo4j()

    def run_sql(text):
        cur.execute(text)
        cur.fetchall()

    def run_cypher(text):
        driver.execute_query(text, timeout=args.timeout)

    rows = []
    for name, q in sql.items():
        print(f"[*] {q['titulo']}")
        try:
            t_sql = measure(lambda: run_sql(q["text"]), args.runs)
        except psycopg2.errors.QueryCanceled:
            t_sql = f"> {args.timeout}s"
        try:
            t_neo = measure(lambda: run_cypher(cypher[name]["text"]), args.runs)
        except Exception as exc:  # noqa: BLE001 - timeout do Neo4j vira ClientError
            if "timeout" not in str(exc).lower() and "terminated" not in str(exc).lower():
                raise
            t_neo = f"> {args.timeout}s"
        print(f"    PostgreSQL: {fmt(t_sql)} ms | Neo4j: {fmt(t_neo)} ms")
        rows.append((q["titulo"], t_sql, t_neo))

    cur.close()
    conn.close()
    driver.close()

    def winner(a, b):
        if isinstance(a, str) and isinstance(b, str):
            return "—"
        if isinstance(a, str):
            return "Neo4j"
        if isinstance(b, str):
            return "PostgreSQL"
        if max(a, b) <= 1.1 * min(a, b):
            return "empate"
        return "PostgreSQL" if a < b else "Neo4j"

    lines = [
        "# Resultados do Benchmark: PostgreSQL vs. Neo4j",
        "",
        f"- Data: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Máquina: {platform.system()} {platform.machine()}, Python {platform.python_version()}",
        f"- Avaliações carregadas: {n_ratings:,}",
        f"- Método: 1 execução de aquecimento + mediana de {args.runs} execuções; "
        f"timeout de {args.timeout}s por execução.",
        "",
        "| Consulta | PostgreSQL (ms) | Neo4j (ms) | Mais rápido |",
        "| :--- | ---: | ---: | :---: |",
    ]
    for titulo, a, b in rows:
        lines.append(f"| {titulo} | {fmt(a)} | {fmt(b)} | {winner(a, b)} |")
    lines.append("")
    open(args.out, "w", encoding="utf-8").write("\n".join(lines))
    print(f"\n[+] Tabela gravada em {args.out}")


if __name__ == "__main__":
    main()
