#!/usr/bin/env python3
"""
scripts/test_cassandra_queries.py
--------------------------------------------------------------------------------
Executa no Cassandra as consultas de cassandra/queries.cql (equivalentes às do
PostgreSQL) e exibe os resultados. Também mostra a consulta que o Cassandra
recusa (top 10 calculado na hora).
--------------------------------------------------------------------------------
"""

from cassandra import InvalidRequest

from common import ROOT, connect_cassandra, load_queries
from test_sql_queries import print_table


def statements(text):
    """Separa um bloco em comandos (uma consulta CQL pode ter mais de uma leitura)."""
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


def run(session, text):
    """Executa todos os comandos do bloco; devolve o resultado de cada um."""
    out = []
    for stmt in statements(text):
        rs = session.execute(stmt)
        out.append((list(rs.column_names or []), [tuple(r) for r in rs]))
    return out


def main():
    cluster, session = connect_cassandra()
    print("=" * 80)
    print("CONSULTAS NO CASSANDRA (CQL)")
    print("=" * 80)
    for q in load_queries(ROOT / "cassandra" / "queries.cql"):
        print(f"\n>>> {q['titulo']}")
        for cols, rows in run(session, q["text"]):
            print_table(cols, rows)

    print("\n>>> Tentativa: top 10 calculado na hora (GROUP BY + ORDER BY por agregação)")
    try:
        session.execute("SELECT movie_id, avg(rating) AS media FROM movielens.ratings_by_movie "
                        "GROUP BY movie_id ORDER BY media DESC LIMIT 10")
    except InvalidRequest as exc:
        print(f"  [recusada pelo Cassandra] {exc.message if hasattr(exc, 'message') else exc}")
    cluster.shutdown()
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
