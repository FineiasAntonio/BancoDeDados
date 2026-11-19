// =============================================================================
// ESQUEMA DO GRAFO - NEO4J 5
// Projeto: Análise Comparativa Relacional vs. NoSQL (Dataset MovieLens)
//
// Modelo (property graph):
//   (:User  {user_id})
//   (:Movie {movie_id, title, release_year, imdb_id, tmdb_id})
//   (:Genre {name})
//   (:Tag   {name})
//   (:User)-[:RATED {rating, rated_at}]->(:Movie)
//   (:Movie)-[:IN_GENRE]->(:Genre)
//   (:Movie)-[:HAS_TAG {count}]->(:Tag)
//
// O Neo4j não tem esquema obrigatório: as constraints abaixo são a única
// "integridade" imposta pelo banco (unicidade + índice implícito).
// Executado automaticamente por scripts/load_neo4j.py.
// =============================================================================

CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (u:User) REQUIRE u.user_id IS UNIQUE;

CREATE CONSTRAINT movie_id_unique IF NOT EXISTS
FOR (m:Movie) REQUIRE m.movie_id IS UNIQUE;

CREATE CONSTRAINT genre_name_unique IF NOT EXISTS
FOR (g:Genre) REQUIRE g.name IS UNIQUE;

CREATE CONSTRAINT tag_name_unique IF NOT EXISTS
FOR (t:Tag) REQUIRE t.name IS UNIQUE;

CREATE INDEX movie_release_year IF NOT EXISTS
FOR (m:Movie) ON (m.release_year);
