-- =============================================================================
-- ESQUEMA DO CASSANDRA - MODELAGEM ORIENTADA A CONSULTAS
-- Projeto: Análise Comparativa Relacional vs. NoSQL (Dataset MovieLens)
--
-- No Cassandra não se modela entidades e depois escreve consultas: parte-se
-- das consultas e cria-se UMA TABELA POR CONSULTA. A mesma informação é
-- gravada várias vezes (desnormalização), cada cópia ordenada para responder
-- uma pergunta lendo uma única partição.
--
-- Executado automaticamente por scripts/load_cassandra.py.
-- =============================================================================

-- Um único nó neste projeto (fator de replicação 1). Em produção: NetworkTopologyStrategy com RF 3.
CREATE KEYSPACE IF NOT EXISTS movielens
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

-- Consulta 1 (ficha do filme): tudo o que é do filme num só registro.
-- Gêneros e tags viram coleções (set) dentro da linha.
CREATE TABLE IF NOT EXISTS movielens.movies (
    movie_id     int PRIMARY KEY,
    title        text,
    release_year int,
    genres       set<text>,
    tags         set<text>,
    imdb_id      text,
    tmdb_id      int
);

-- Consulta 1 (média e total de votos): contadores atualizados a cada avaliação.
-- Contadores não aceitam decimais: a soma é guardada em meias estrelas (nota * 2).
CREATE TABLE IF NOT EXISTS movielens.movie_stats (
    movie_id       int PRIMARY KEY,
    half_stars_sum counter,
    rating_count   counter
);

-- Consulta 2 (top 10): o Cassandra não ordena por agregação, então o ranking
-- é calculado na carga e gravado já ordenado numa única partição.
CREATE TABLE IF NOT EXISTS movielens.top_movies (
    bucket       text,
    avg_rating   double,
    vote_count   int,
    movie_id     int,
    title        text,
    release_year int,
    PRIMARY KEY ((bucket), avg_rating, vote_count, movie_id)
) WITH CLUSTERING ORDER BY (avg_rating DESC, vote_count DESC, movie_id ASC);

-- Consulta 3 (por gênero): agregação calculada na carga.
CREATE TABLE IF NOT EXISTS movielens.genre_stats (
    genre         text PRIMARY KEY,
    total_movies  int,
    total_ratings bigint,
    avg_rating    double
);

-- Consulta 4 (busca por tags): a tag é a chave de partição.
CREATE TABLE IF NOT EXISTS movielens.movies_by_tag (
    tag          text,
    movie_id     int,
    title        text,
    release_year int,
    PRIMARY KEY ((tag), movie_id)
);

-- Consulta 5 (histórico do usuário): uma partição por usuário, mais recentes primeiro.
CREATE TABLE IF NOT EXISTS movielens.ratings_by_user (
    user_id  int,
    rated_at timestamp,
    movie_id int,
    rating   float,
    PRIMARY KEY ((user_id), rated_at, movie_id)
) WITH CLUSTERING ORDER BY (rated_at DESC, movie_id ASC);

-- Consulta 6 (avaliações de um filme num período): uma partição por filme, ordenada por data.
CREATE TABLE IF NOT EXISTS movielens.ratings_by_movie (
    movie_id int,
    rated_at timestamp,
    user_id  int,
    rating   float,
    PRIMARY KEY ((movie_id), rated_at, user_id)
) WITH CLUSTERING ORDER BY (rated_at DESC, user_id ASC);
