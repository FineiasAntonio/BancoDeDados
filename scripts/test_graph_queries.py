#!/usr/bin/env python3
"""
scripts/test_graph_queries.py
--------------------------------------------------------------------------------
Executa no Neo4j as consultas de neo4j/queries.cypher (equivalentes às do
PostgreSQL) e exibe os resultados no terminal.
--------------------------------------------------------------------------------
"""

from common import ROOT, connect_neo4j, load_queries
from test_sql_queries import print_table


def main():
    driver = connect_neo4j()
    print("=" * 80)
    print("CONSULTAS NO MODELO EM GRAFO - NEO4J (CYPHER)")
    print("=" * 80)
    for q in load_queries(ROOT / "neo4j" / "queries.cypher"):
        print(f"\n>>> {q['titulo']}")
        records, _, keys = driver.execute_query(q["text"])
        print_table(keys, [r.values() for r in records])
    driver.close()
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
