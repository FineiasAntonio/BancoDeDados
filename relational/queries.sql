-- =============================================================================
-- CONSULTAS DE COMPARAÇÃO - MODELO RELACIONAL (3FN) - POSTGRESQL
-- Equivalentes, uma a uma, às de cassandra/queries.cql.
-- Executável com: psql -h localhost -U postgres -d movielens -f relational/queries.sql
-- Os marcadores "-- name:" são lidos por scripts/test_sql_queries.py e scripts/benchmark.py.
-- =============================================================================


-- name: c1_ficha
-- titulo: Consulta 1 - Ficha completa de um filme (Toy Story)
-- As avaliações são agregadas numa subconsulta: juntá-las diretamente com
-- movie_genres multiplicaria cada avaliação pelo número de gêneros do filme.
SELECT
    m.movie_id,
    m.title,
    m.release_year,
    l.imdb_id,
    l.tmdb_id,
    (SELECT string_agg(g.name, ', ' ORDER BY g.name)
       FROM movie_genres mg JOIN genres g ON g.genre_id = mg.genre_id
      WHERE mg.movie_id = m.movie_id)                      AS genres,
    r.total_ratings,
    r.avg_rating
FROM movies m
LEFT JOIN movie_links l ON l.movie_id = m.movie_id
CROSS JOIN LATERAL (
    SELECT COUNT(*) AS total_ratings, ROUND(AVG(rating), 2) AS avg_rating
      FROM ratings WHERE movie_id = m.movie_id
) r
WHERE m.movie_id = 1;


-- name: c2_top10
-- titulo: Consulta 2 - Top 10 filmes mais bem avaliados (mínimo de 50 votos)
SELECT
    m.movie_id,
    m.title,
    m.release_year,
    COUNT(*)                AS vote_count,
    ROUND(AVG(r.rating), 3) AS average_rating
FROM movies m
JOIN ratings r ON r.movie_id = m.movie_id
GROUP BY m.movie_id, m.title, m.release_year
HAVING COUNT(*) >= 50
ORDER BY AVG(r.rating) DESC, vote_count DESC, m.movie_id
LIMIT 10;


-- name: c3_generos
-- titulo: Consulta 3 - Total de filmes e média das avaliações por gênero
-- A média é sobre todas as avaliações dos filmes do gênero (filmes com mais votos pesam mais).
SELECT
    g.name                       AS genre,
    COUNT(DISTINCT mg.movie_id)  AS total_movies,
    COUNT(r.rating)              AS total_ratings,
    ROUND(AVG(r.rating), 2)      AS avg_genre_rating
FROM genres g
JOIN movie_genres mg ON mg.genre_id = g.genre_id
LEFT JOIN ratings r  ON r.movie_id = mg.movie_id
GROUP BY g.genre_id, g.name
ORDER BY total_movies DESC, genre;


-- name: c4_tags
-- titulo: Consulta 4 - Filmes marcados com 'pixar' ou 'animation'
SELECT
    m.movie_id,
    m.title,
    m.release_year,
    string_agg(DISTINCT t.tag_name, ', ') AS matched_tags
FROM movies m
JOIN user_movie_tags umt ON umt.movie_id = m.movie_id
JOIN tags t              ON t.tag_id = umt.tag_id
WHERE t.tag_name IN ('pixar', 'animation')
GROUP BY m.movie_id, m.title, m.release_year
ORDER BY m.movie_id
LIMIT 20;


-- name: c5_historico_usuario
-- titulo: Consulta 5 - Histórico recente do usuário 42 (últimas 20 avaliações)
-- Usa o índice (user_id, rated_at) de ratings.
SELECT r.movie_id, r.rating, r.rated_at
FROM ratings r
WHERE r.user_id = 42
ORDER BY r.rated_at DESC, r.movie_id
LIMIT 20;


-- name: c6_periodo_filme
-- titulo: Consulta 6 - Avaliações de Toy Story em janeiro de 2015
-- Usa o índice (movie_id, rated_at) de ratings.
SELECT r.user_id, r.rating, r.rated_at
FROM ratings r
WHERE r.movie_id = 1
  AND r.rated_at >= '2015-01-01'
  AND r.rated_at <  '2015-02-01'
ORDER BY r.rated_at DESC, r.user_id;
