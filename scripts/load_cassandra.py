#!/usr/bin/env python3
"""
scripts/load_cassandra.py
--------------------------------------------------------------------------------
ETL dos dados brutos do MovieLens (data/raw/) para o Cassandra.

Modelagem orientada a consultas (ver cassandra/schema.cql):
  - cada avaliação é gravada em DUAS tabelas (ratings_by_user e ratings_by_movie)
    e soma nos contadores de movie_stats;
  - o que o Cassandra não sabe agregar (top 10, médias por gênero) é calculado
    aqui, na carga, e gravado pronto em top_movies e genre_stats.

Re-executável: apaga o keyspace antes de carregar.
--------------------------------------------------------------------------------
"""

import argparse
import os
import time

import pandas as pd
from cassandra.concurrent import execute_concurrent, execute_concurrent_with_args
from cassandra.query import BatchStatement, BatchType

from common import ROOT, connect_cassandra, extract_title_and_year


BATCH_ROWS = 100  # linhas por lote; lotes grandes demais geram alerta no Cassandra


def parse_args():
    p = argparse.ArgumentParser(description="ETL MovieLens -> Cassandra")
    p.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--concurrency", type=int, default=32,
                   help="Escritas simultâneas em andamento (o driver faz o paralelismo).")
    p.add_argument("--sample-ratings", type=int, default=100000,
                   help="Limite de ratings (padrão: 100000). 0 ou --all-ratings carrega os 20M.")
    p.add_argument("--all-ratings", action="store_true")
    return p.parse_args()


def run_schema(session):
    session.execute("DROP KEYSPACE IF EXISTS movielens", timeout=120)
    text = (ROOT / "cassandra" / "schema.cql").read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
    for stmt in filter(None, (s.strip() for s in body.split(";"))):
        session.execute(stmt, timeout=120)
    session.set_keyspace("movielens")
    print("[+] keyspace e tabelas criados")


def write(session, cql, rows, concurrency):
    """Grava em paralelo; falha alta se alguma escrita der erro."""
    stmt = session.prepare(cql)
    for ok, result in execute_concurrent_with_args(session, stmt, rows, concurrency=concurrency,
                                                   raise_on_first_error=True):
        pass
    return len(rows)


def load_movies(session, raw_dir, concurrency):
    movies = pd.read_csv(os.path.join(raw_dir, "movie.csv"))
    links = pd.read_csv(os.path.join(raw_dir, "link.csv"), dtype={"imdbId": str})
    links = {int(m): (i.zfill(7) if pd.notna(i) else None, int(t) if pd.notna(t) else None)
             for m, i, t in zip(links["movieId"], links["imdbId"], links["tmdbId"])}

    tags = pd.read_csv(os.path.join(raw_dir, "tag.csv")).dropna(subset=["tag"])
    tags["tag"] = tags["tag"].astype(str).str.strip().str.lower()
    tags = tags[tags["tag"] != ""]
    tags_by_movie = tags.groupby("movieId")["tag"].agg(lambda s: set(s)).to_dict()

    info, movie_rows, genres_of = {}, [], {}
    for mid, raw_title, raw_genres in movies.itertuples(index=False):
        mid = int(mid)
        title, year = extract_title_and_year(raw_title)
        genres = {g.strip() for g in str(raw_genres).split("|")
                  if g.strip() and g.strip() != "(no genres listed)"}
        imdb, tmdb = links.get(mid, (None, None))
        info[mid] = (title, year)
        genres_of[mid] = genres
        movie_rows.append((mid, title, year, genres or None, tags_by_movie.get(mid) or None, imdb, tmdb))
    write(session, "INSERT INTO movies (movie_id, title, release_year, genres, tags, imdb_id, tmdb_id) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)", movie_rows, concurrency)

    pairs = tags[["movieId", "tag"]].drop_duplicates()
    tag_rows = [(t, int(m), *info[int(m)]) for m, t in pairs.itertuples(index=False) if int(m) in info]
    write(session, "INSERT INTO movies_by_tag (tag, movie_id, title, release_year) VALUES (?, ?, ?, ?)",
          tag_rows, concurrency)
    print(f"[+] movies={len(movie_rows):,} movies_by_tag={len(tag_rows):,}")
    return info, genres_of


def load_ratings(session, raw_dir, concurrency, limit):
    by_user = session.prepare("INSERT INTO ratings_by_user (user_id, rated_at, movie_id, rating) VALUES (?, ?, ?, ?)")
    by_movie = session.prepare("INSERT INTO ratings_by_movie (movie_id, rated_at, user_id, rating) VALUES (?, ?, ?, ?)")
    total = 0
    half_stars = pd.Series(dtype="int64")
    counts = pd.Series(dtype="int64")
    t0 = time.time()
    for chunk in pd.read_csv(os.path.join(raw_dir, "rating.csv"), chunksize=200_000):
        if limit:
            chunk = chunk.iloc[: limit - total]
        g = chunk.groupby("movieId")["rating"]
        half_stars = half_stars.add((g.sum() * 2).round().astype("int64"), fill_value=0)
        counts = counts.add(g.count(), fill_value=0)

        rated_at = pd.to_datetime(chunk["timestamp"], unit="s").dt.to_pydatetime()
        df = pd.DataFrame({"u": chunk["userId"].to_numpy(), "m": chunk["movieId"].to_numpy(),
                           "r": chunk["rating"].to_numpy(), "t": rated_at})
        # Lotes por partição (BATCH UNLOGGED): todas as linhas de um lote vão para o
        # mesmo nó e a mesma partição, então o Cassandra grava tudo de uma vez.
        batches = []
        for key, stmt, cols in (("u", by_user, ("u", "t", "m", "r")), ("m", by_movie, ("m", "t", "u", "r"))):
            for _, part in df.groupby(key, sort=False):
                rows = list(zip(*(part[c].tolist() for c in cols)))
                for i in range(0, len(rows), BATCH_ROWS):
                    b = BatchStatement(batch_type=BatchType.UNLOGGED)
                    for row in rows[i:i + BATCH_ROWS]:
                        b.add(stmt, (int(row[0]), row[1], int(row[2]), float(row[3])))
                    batches.append((b, ()))
        for ok, result in execute_concurrent(session, batches, concurrency=concurrency, raise_on_first_error=True):
            pass
        total += len(chunk)
        print(f"    - {total:,} ratings ({total / (time.time() - t0):,.0f} avaliações/s, 2 escritas cada)")
        if limit and total >= limit:
            break
    print(f"[+] ratings={total:,} (ratings_by_user + ratings_by_movie)")
    return half_stars.astype("int64"), counts.astype("int64")


def load_aggregates(session, info, genres_of, half_stars, counts, concurrency):
    # Contadores: uma atualização por filme com o total da carga.
    stats = [(int(half_stars[m]), int(counts[m]), int(m)) for m in counts.index]
    write(session, "UPDATE movie_stats SET half_stars_sum = half_stars_sum + ?, rating_count = rating_count + ? "
                   "WHERE movie_id = ?", stats, concurrency)

    # Top 10: ranking pronto, numa única partição, já ordenado pela chave de clustering.
    top = [("all", (half_stars[m] / 2) / counts[m], int(counts[m]), int(m), *info[int(m)])
           for m in counts.index if counts[m] >= 50 and int(m) in info]
    write(session, "INSERT INTO top_movies (bucket, avg_rating, vote_count, movie_id, title, release_year) "
                   "VALUES (?, ?, ?, ?, ?, ?)", top, concurrency)

    # Por gênero: total de filmes, total de avaliações e média ponderada.
    acc = {}
    for mid, genres in genres_of.items():
        n = int(counts.get(mid, 0))
        hs = int(half_stars.get(mid, 0))
        for gname in genres:
            a = acc.setdefault(gname, [0, 0, 0])
            a[0] += 1
            a[1] += n
            a[2] += hs
    genre_rows = [(gname, a[0], a[1], (a[2] / 2) / a[1] if a[1] else None) for gname, a in acc.items()]
    write(session, "INSERT INTO genre_stats (genre, total_movies, total_ratings, avg_rating) VALUES (?, ?, ?, ?)",
          genre_rows, concurrency)
    print(f"[+] movie_stats={len(stats):,} top_movies={len(top):,} genre_stats={len(genre_rows):,}")


def main():
    args = parse_args()
    t0 = time.time()
    limit = 0 if args.all_ratings else args.sample_ratings
    cluster, session = connect_cassandra(args.host)
    try:
        run_schema(session)
        info, genres_of = load_movies(session, args.raw_dir, args.concurrency)
        half_stars, counts = load_ratings(session, args.raw_dir, args.concurrency, limit)
        load_aggregates(session, info, genres_of, half_stars, counts, args.concurrency)
    finally:
        cluster.shutdown()
    print(f"[+] Concluído em {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
