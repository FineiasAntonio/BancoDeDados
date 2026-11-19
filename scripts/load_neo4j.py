#!/usr/bin/env python3
"""
scripts/load_neo4j.py
--------------------------------------------------------------------------------
ETL dos dados brutos do MovieLens (data/raw/) para o Neo4j (grafo de propriedades).

Modelo:
  (:User)-[:RATED {rating, rated_at}]->(:Movie)
  (:Movie)-[:IN_GENRE]->(:Genre)
  (:Movie)-[:HAS_TAG {count}]->(:Tag)
  Links externos (imdb_id, tmdb_id) viram propriedades do nó :Movie (relação 1:1).

Re-executável: apaga o grafo antes de carregar. Carga em lotes com UNWIND.
--------------------------------------------------------------------------------
"""

import argparse
import os
import time

import pandas as pd

from common import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, ROOT, connect_neo4j, extract_title_and_year


def parse_args():
    p = argparse.ArgumentParser(description="ETL MovieLens -> Neo4j")
    p.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    p.add_argument("--uri", default=NEO4J_URI)
    p.add_argument("--user", default=NEO4J_USER)
    p.add_argument("--password", default=NEO4J_PASSWORD)
    p.add_argument("--batch-size", type=int, default=10000)
    p.add_argument("--sample-ratings", type=int, default=100000,
                   help="Limite de ratings (padrão: 100000). 0 ou --all-ratings carrega os 20M.")
    p.add_argument("--all-ratings", action="store_true")
    return p.parse_args()


def run_batches(session, cypher, rows, batch_size):
    for i in range(0, len(rows), batch_size):
        session.run(cypher, rows=rows[i:i + batch_size]).consume()


def reset_graph(session):
    """Apaga tudo em transações menores (DETACH DELETE de milhões de arestas de uma vez estoura memória)."""
    session.run("""
        MATCH (n)
        CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS
    """).consume()


def create_schema(session):
    text = (ROOT / "neo4j" / "schema.cypher").read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))
    for stmt in filter(None, (s.strip() for s in body.split(";"))):
        session.run(stmt).consume()
    session.run("CALL db.awaitIndexes(300)").consume()
    print("[+] constraints e índices criados")


def load_movies(session, raw_dir, batch_size):
    df = pd.read_csv(os.path.join(raw_dir, "movie.csv"))
    links = pd.read_csv(os.path.join(raw_dir, "link.csv"), dtype={"imdbId": str})
    links = {
        int(m): (i.zfill(7) if pd.notna(i) else None, int(t) if pd.notna(t) else None)
        for m, i, t in zip(links["movieId"], links["imdbId"], links["tmdbId"])
    }

    movies, genre_links = [], []
    for mid, raw_title, raw_genres in df.itertuples(index=False):
        mid = int(mid)
        title, year = extract_title_and_year(raw_title)
        imdb, tmdb = links.get(mid, (None, None))
        movies.append({"id": mid, "title": title, "year": year, "imdb": imdb, "tmdb": tmdb})
        for g in str(raw_genres).split("|"):
            g = g.strip()
            if g and g != "(no genres listed)":
                genre_links.append({"m": mid, "g": g})

    run_batches(session, """
        UNWIND $rows AS row
        CREATE (:Movie {movie_id: row.id, title: row.title, release_year: row.year,
                        imdb_id: row.imdb, tmdb_id: row.tmdb})
    """, movies, batch_size)

    genres = sorted({r["g"] for r in genre_links})
    session.run("UNWIND $names AS name CREATE (:Genre {name: name})", names=genres).consume()
    run_batches(session, """
        UNWIND $rows AS row
        MATCH (m:Movie {movie_id: row.m}), (g:Genre {name: row.g})
        CREATE (m)-[:IN_GENRE]->(g)
    """, genre_links, batch_size)
    print(f"[+] movies={len(movies):,} genres={len(genres):,} IN_GENRE={len(genre_links):,}")


def load_tags(session, raw_dir, batch_size):
    df = pd.read_csv(os.path.join(raw_dir, "tag.csv")).dropna(subset=["tag"])
    df["tag"] = df["tag"].astype(str).str.strip().str.lower()
    df = df[df["tag"] != ""]

    tags = sorted(df["tag"].unique())
    run_batches(session, "UNWIND $rows AS name CREATE (:Tag {name: name})", tags, batch_size)

    # Uma aresta por par (filme, tag), com o número de usuários que aplicaram a tag.
    pairs = df.groupby(["movieId", "tag"]).size().reset_index(name="n")
    rows = [{"m": int(m), "t": t, "n": int(n)} for m, t, n in pairs.itertuples(index=False)]
    run_batches(session, """
        UNWIND $rows AS row
        MATCH (m:Movie {movie_id: row.m}), (t:Tag {name: row.t})
        CREATE (m)-[:HAS_TAG {count: row.n}]->(t)
    """, rows, batch_size)
    print(f"[+] tags={len(tags):,} HAS_TAG={len(rows):,}")


def load_ratings(session, raw_dir, batch_size, limit):
    total, users = 0, set()
    for chunk in pd.read_csv(os.path.join(raw_dir, "rating.csv"), chunksize=200_000):
        if limit:
            chunk = chunk.iloc[: limit - total]

        new_users = [int(u) for u in chunk["userId"].unique() if u not in users]
        users.update(new_users)
        run_batches(session, "UNWIND $rows AS id CREATE (:User {user_id: id})", new_users, batch_size)

        rated_at = pd.to_datetime(chunk["timestamp"], unit="s").dt.to_pydatetime()
        rows = [
            {"u": u, "m": m, "r": r, "t": t}
            for u, m, r, t in zip(chunk["userId"].tolist(), chunk["movieId"].tolist(),
                                  chunk["rating"].tolist(), rated_at)
        ]
        run_batches(session, """
            UNWIND $rows AS row
            MATCH (u:User {user_id: row.u}), (m:Movie {movie_id: row.m})
            CREATE (u)-[:RATED {rating: row.r, rated_at: row.t}]->(m)
        """, rows, batch_size)

        total += len(rows)
        print(f"    - {total:,} ratings...")
        if limit and total >= limit:
            break
    print(f"[+] ratings={total:,} users={len(users):,}")


def main():
    args = parse_args()
    t0 = time.time()
    limit = 0 if args.all_ratings else args.sample_ratings

    driver = connect_neo4j(args.uri, args.user, args.password)
    try:
        with driver.session() as session:
            reset_graph(session)
            create_schema(session)
            load_movies(session, args.raw_dir, args.batch_size)
            load_tags(session, args.raw_dir, args.batch_size)
            load_ratings(session, args.raw_dir, args.batch_size, limit)
    finally:
        driver.close()
    print(f"[+] Concluído em {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
