-- =============================================================================
-- CONSULTAS DE COMPARAÇÃO - CASSANDRA (CQL)
-- Equivalentes, uma a uma, às de relational/queries.sql.
-- Executável com: cqlsh -f cassandra/queries.cql
-- Os marcadores "-- name:" são lidos por scripts/test_cassandra_queries.py e scripts/benchmark.py.
-- Uma consulta pode ter mais de um comando (separados por ";"): a aplicação faz as duas leituras.
-- =============================================================================


-- name: c1_ficha
-- titulo: Consulta 1 - Ficha completa de um filme (Toy Story)
-- Duas leituras por chave: o filme (com gêneros e tags na própria linha) e os contadores.
-- A média é calculada na aplicação: half_stars_sum / 2 / rating_count.
SELECT movie_id, title, release_year, imdb_id, tmdb_id, genres
FROM movielens.movies WHERE movie_id = 1;
SELECT half_stars_sum, rating_count
FROM movielens.movie_stats WHERE movie_id = 1;


-- name: c2_top10
-- titulo: Consulta 2 - Top 10 filmes mais bem avaliados (mínimo de 50 votos)
-- O CQL não tem como fazer esta consulta na hora:
--   SELECT movie_id, avg(rating) FROM movielens.ratings_by_movie
--   GROUP BY movie_id ORDER BY avg(rating) DESC LIMIT 10;
--   -> SyntaxException: ORDER BY não aceita agregações, só colunas de ordenação (clustering);
--   e mesmo ORDER BY rated_at falha: "ORDER BY is only supported when the partition key
--   is restricted by an EQ or an IN" (só se ordena dentro de uma partição).
-- Por isso o ranking é calculado na carga e lido pronto, já ordenado, de uma única partição.
SELECT movie_id, title, release_year, vote_count, avg_rating
FROM movielens.top_movies WHERE bucket = 'all' LIMIT 10;


-- name: c3_generos
-- titulo: Consulta 3 - Total de filmes e média das avaliações por gênero
-- Também pré-calculada na carga. A ordenação por total_movies fica com a aplicação.
SELECT genre, total_movies, total_ratings, avg_rating
FROM movielens.genre_stats;


-- name: c4_tags
-- titulo: Consulta 4 - Filmes marcados com 'pixar' ou 'animation'
-- IN é permitido porque tag é a chave de partição: lê exatamente duas partições.
SELECT tag, movie_id, title, release_year
FROM movielens.movies_by_tag WHERE tag IN ('pixar', 'animation');


-- name: c5_historico_usuario
-- titulo: Consulta 5 - Histórico recente do usuário 42 (últimas 20 avaliações)
-- Lê o começo de uma única partição, que já está gravada do mais recente para o mais antigo.
SELECT movie_id, rating, rated_at
FROM movielens.ratings_by_user WHERE user_id = 42 LIMIT 20;


-- name: c6_periodo_filme
-- titulo: Consulta 6 - Avaliações de Toy Story em janeiro de 2015
-- Faixa contínua dentro de uma partição, porque rated_at é coluna de ordenação (clustering).
SELECT user_id, rating, rated_at
FROM movielens.ratings_by_movie
WHERE movie_id = 1
  AND rated_at >= '2015-01-01 00:00:00+0000'
  AND rated_at <  '2015-02-01 00:00:00+0000';
