#!/usr/bin/env python3
"""
scripts/test_sql_queries.py
--------------------------------------------------------------------------------
Executa no PostgreSQL as consultas de relational/queries.sql e exibe os
resultados no terminal, para comparação com o Cassandra (test_cassandra_queries.py).
--------------------------------------------------------------------------------
"""

import argparse

import psycopg2

from common import ROOT, connect, load_queries


def print_table(columns, rows):
    if not rows:
        print("  (nenhuma linha)")
        return
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(columns)]
    print("  " + " | ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  " + "-+-".join("-" * w for w in widths))
    for r in cells:
        print("  " + " | ".join(v.ljust(w) for v, w in zip(r, widths)))


def main():
    p = argparse.ArgumentParser(description="Consultas de comparação no PostgreSQL")
    p.add_argument("--timeout", type=int, default=60, help="Timeout por consulta, em segundos.")
    args = p.parse_args()

    conn = connect()
    conn.autocommit = True
    print("=" * 80)
    print("CONSULTAS NO MODELO RELACIONAL (3FN) - POSTGRESQL")
    print("=" * 80)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = '{args.timeout}s'")
        for q in load_queries(ROOT / "relational" / "queries.sql"):
            print(f"\n>>> {q['titulo']}")
            try:
                cur.execute(q["text"])
                print_table([d.name for d in cur.description], cur.fetchall())
            except psycopg2.errors.QueryCanceled:
                print(f"  [!] Cancelada: passou do limite de {args.timeout}s.")
    conn.close()
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
