#!/usr/bin/env python3
"""
scripts/build_similarity.py
--------------------------------------------------------------------------------
Pré-calcula a similaridade entre filmes e grava como aresta no grafo:

    (:Movie)-[:SIMILAR {score}]->(:Movie)

Dois filmes são parecidos quando as mesmas pessoas gostaram dos dois (nota >= 4).
Score = similaridade de Jaccard entre os conjuntos de usuários:
    |gostaram de A e de B| / |gostaram de A ou de B|
Para cada filme, guarda os --top-k mais parecidos.

Roda UMA vez, depois de load_neo4j.py. A partir daí, "quem gostou deste também
gostou de..." vira um único salto: (:Movie)-[:SIMILAR]->(:Movie).

O cálculo é feito em Python (matriz esparsa) para não depender de plugins. Com o
plugin Graph Data Science do Neo4j, o equivalente seria gds.nodeSimilarity.write.
--------------------------------------------------------------------------------
"""

import argparse
import time

import numpy as np
from scipy import sparse

from common import connect_neo4j


def parse_args():
    p = argparse.ArgumentParser(description="Pré-calcula arestas SIMILAR entre filmes")
    p.add_argument("--min-rating", type=float, default=4.0, help="Nota mínima para contar como 'gostou'.")
    p.add_argument("--min-likes", type=int, default=20,
                   help="Ignora filmes com menos curtidas que isso (similaridade pouco confiável).")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--block", type=int, default=1000, help="Filmes por bloco no cálculo (controla a memória).")
    p.add_argument("--batch-size", type=int, default=10000)
    return p.parse_args()


def main():
    args = parse_args()
    driver = connect_neo4j()
    t0 = time.time()

    # 1. Lê do grafo quem gostou de quê
    users, movies = [], []
    with driver.session() as s:
        result = s.run("MATCH (u:User)-[r:RATED]->(m:Movie) WHERE r.rating >= $min "
                       "RETURN u.user_id AS u, m.movie_id AS m", min=args.min_rating)
        for rec in result:
            users.append(rec[0])
            movies.append(rec[1])
    t_read = time.time() - t0
    print(f"[+] {len(users):,} curtidas lidas em {t_read:.1f}s")

    # 2. Matriz filmes x usuários (1 = gostou)
    movie_ids, m_idx = np.unique(np.asarray(movies), return_inverse=True)
    _, u_idx = np.unique(np.asarray(users), return_inverse=True)
    X = sparse.csr_matrix((np.ones(len(m_idx), dtype=np.float32), (m_idx, u_idx)))
    likes = np.asarray(X.sum(axis=1)).ravel()
    keep = np.where(likes >= args.min_likes)[0]
    X = X[keep]
    likes = likes[keep]
    movie_ids = movie_ids[keep]
    XT = X.T.tocsr()
    print(f"[+] {len(movie_ids):,} filmes com pelo menos {args.min_likes} curtidas")

    # 3. Jaccard em blocos: co-ocorrência = X . X^T
    t1 = time.time()
    edges = []
    for start in range(0, X.shape[0], args.block):
        stop = min(start + args.block, X.shape[0])
        co = (X[start:stop] @ XT).toarray()                      # bloco x filmes
        union = likes[start:stop, None] + likes[None, :] - co
        jac = np.divide(co, union, out=np.zeros_like(co), where=union > 0)
        jac[np.arange(stop - start), np.arange(start, stop)] = 0  # ignora o próprio filme
        top = np.argpartition(-jac, args.top_k, axis=1)[:, :args.top_k]
        for i, row in enumerate(top):
            for j in row:
                if jac[i, j] > 0:
                    edges.append({"a": int(movie_ids[start + i]), "b": int(movie_ids[j]),
                                  "s": round(float(jac[i, j]), 4)})
    t_calc = time.time() - t1
    print(f"[+] {len(edges):,} pares calculados em {t_calc:.1f}s")

    # 4. Grava as arestas no grafo
    t2 = time.time()
    with driver.session() as s:
        s.run("MATCH ()-[r:SIMILAR]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 50000 ROWS").consume()
        for i in range(0, len(edges), args.batch_size):
            s.run("""
                UNWIND $rows AS row
                MATCH (a:Movie {movie_id: row.a}), (b:Movie {movie_id: row.b})
                CREATE (a)-[:SIMILAR {score: row.s}]->(b)
            """, rows=edges[i:i + args.batch_size]).consume()
    t_write = time.time() - t2
    driver.close()
    print(f"[+] arestas SIMILAR gravadas em {t_write:.1f}s")
    print(f"[+] Concluído em {time.time() - t0:.1f}s "
          f"(leitura {t_read:.0f}s, cálculo {t_calc:.0f}s, gravação {t_write:.0f}s)")


if __name__ == "__main__":
    main()
