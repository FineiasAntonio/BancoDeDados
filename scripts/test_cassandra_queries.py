#!/usr/bin/env python3
"""
scripts/test_cassandra_queries.py
--------------------------------------------------------------------------------
Executa no Cassandra as consultas de cassandra/queries.cql (equivalentes às do
PostgreSQL) e exibe os resultados. Também mostra a consulta que o Cassandra
recusa (top 10 calculado na hora).
--------------------------------------------------------------------------------
"""

from cassandra.protocol import SyntaxException
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

    print("\n>>> Tentativas que o Cassandra recusa")
    for cql in ("SELECT movie_id, avg(rating) FROM movielens.ratings_by_movie "
                "GROUP BY movie_id ORDER BY avg(rating) DESC LIMIT 10",
                "SELECT movie_id, avg(rating) FROM movielens.ratings_by_movie "
                "GROUP BY movie_id ORDER BY rated_at DESC LIMIT 10",
                "SELECT movie_id, rating FROM movielens.ratings_by_user WHERE user_id = 42 AND rating = 5"):
        try:
            session.execute(cql)
        except (InvalidRequest, SyntaxException) as exc:
            msg = str(exc)
            print(f"  {cql}\n    -> {msg[msg.find('message'):][:170]}")
    cluster.shutdown()
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
