// =============================================================================
// CONSULTAS DE COMPARAÇÃO - MODELO EM GRAFO - NEO4J (CYPHER)
// Equivalentes, uma a uma, às de relational/queries.sql.
// Executável com:
//   cypher-shell -a bolt://localhost:7687 -u neo4j -p neo4jpassword -f neo4j/queries.cypher
// Os marcadores "// name:" são lidos por scripts/test_graph_queries.py e scripts/benchmark.py.
// =============================================================================


// name: c1_ficha
// titulo: Consulta 1 - Ficha completa de um filme (Toy Story)
// Gêneros e avaliações são vizinhos diretos do nó do filme: não há tabela de junção.
MATCH (m:Movie {movie_id: 1})
OPTIONAL MATCH (m)-[:IN_GENRE]->(g:Genre)
WITH m, g ORDER BY g.name
WITH m, collect(g.name) AS genres
OPTIONAL MATCH (:User)-[r:RATED]->(m)
RETURN m.movie_id AS movie_id, m.title AS title, m.release_year AS release_year,
       m.imdb_id AS imdb_id, m.tmdb_id AS tmdb_id, genres,
       count(r) AS total_ratings, round(avg(r.rating), 2) AS avg_rating;


// name: c2_top10
// titulo: Consulta 2 - Top 10 filmes mais bem avaliados (mínimo de 50 votos)
// Agregação sobre TODAS as arestas RATED do grafo: é o terreno do SQL.
MATCH (:User)-[r:RATED]->(m:Movie)
WITH m, count(r) AS vote_count, avg(r.rating) AS media
WHERE vote_count >= 50
RETURN m.movie_id AS movie_id, m.title AS title, m.release_year AS release_year,
       vote_count, round(media, 3) AS average_rating
ORDER BY media DESC, vote_count DESC, movie_id
LIMIT 10;


// name: c3_generos
// titulo: Consulta 3 - Total de filmes e média das avaliações por gênero
MATCH (g:Genre)<-[:IN_GENRE]-(m:Movie)
OPTIONAL MATCH (:User)-[r:RATED]->(m)
WITH g, count(DISTINCT m) AS total_movies, count(r) AS total_ratings, avg(r.rating) AS media
RETURN g.name AS genre, total_movies, total_ratings, round(media, 2) AS avg_genre_rating
ORDER BY total_movies DESC, genre;


// name: c4_tags
// titulo: Consulta 4 - Filmes marcados com 'pixar' ou 'animation'
MATCH (m:Movie)-[:HAS_TAG]->(t:Tag)
WHERE t.name IN ['pixar', 'animation']
WITH m, t.name AS tag ORDER BY tag
WITH m, collect(tag) AS matched_tags
RETURN m.movie_id AS movie_id, m.title AS title, m.release_year AS release_year, matched_tags
ORDER BY movie_id
LIMIT 20;


// name: c5_recomendacao
// titulo: Consulta 5 - "Quem gostou de Toy Story também gostou de..." (2 saltos)
// O padrão desenhado na consulta é o próprio caminho percorrido no grafo.
MATCH (:Movie {movie_id: 1})<-[r1:RATED]-(u:User)-[r2:RATED]->(rec:Movie)
WHERE r1.rating >= 4 AND r2.rating >= 4
RETURN rec.movie_id AS movie_id, rec.title AS title, count(u) AS score
ORDER BY score DESC, movie_id
LIMIT 10;


// name: c6_similares_tags
// titulo: Consulta 6 - Filmes com mais tags em comum com Toy Story
MATCH (:Movie {movie_id: 1})-[:HAS_TAG]->(t:Tag)<-[:HAS_TAG]-(o:Movie)
WITH o, t.name AS tag ORDER BY tag
RETURN o.movie_id AS movie_id, o.title AS title, count(*) AS tags_em_comum, collect(tag) AS tags
ORDER BY tags_em_comum DESC, movie_id
LIMIT 10;


// name: c7_caminho
// titulo: Consulta 7 - Menor caminho de Toy Story (1) até The Godfather (858) via tags em comum
// shortestPath faz uma busca em largura bidirecional nativa, sem materializar todos os caminhos.
// distancia = número de "saltos" entre filmes (cada salto passa por uma tag).
MATCH (a:Movie {movie_id: 1}), (b:Movie {movie_id: 858})
MATCH p = shortestPath((a)-[:HAS_TAG*..10]-(b))
RETURN length(p) / 2 AS distancia,
       [n IN nodes(p) | coalesce(n.title, '#' + n.name)] AS caminho;
