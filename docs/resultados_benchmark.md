# Resultados do Benchmark: PostgreSQL vs. Cassandra

- Data: 2026-11-19 15:54
- Máquina: Linux x86_64, Python 3.13.18
- Avaliações carregadas: 20.000.263
- Leitura: 1 aquecimento + média de 10 execuções (ms).

| Consulta | PostgreSQL (ms) | Cassandra (ms) | Mais rápido |
| :--- | ---: | ---: | :---: |
| Consulta 1 - Ficha completa de um filme (Toy Story) | 55,1 | 3,3 | Cassandra |
| Consulta 2 - Top 10 filmes mais bem avaliados (mínimo de 50 votos) | 3.080,2 | 1,7 | Cassandra |
| Consulta 3 - Total de filmes e média das avaliações por gênero | 56.103,3 | 1,7 | Cassandra |
| Consulta 4 - Filmes marcados com 'pixar' ou 'animation' | 5,4 | 3,0 | Cassandra |
| Consulta 5 - Histórico recente do usuário 42 (últimas 20 avaliações) | 0,2 | 1,6 | PostgreSQL |
| Consulta 6 - Avaliações de Toy Story em janeiro de 2015 | 0,6 | 2,4 | PostgreSQL |

## Escrita: 100.000 avaliações novas. 16 simultâneas

| | PostgreSQL | Cassandra | Mais rápido |
| :--- | ---: | ---: | :---: |
| Avaliações por segundo | 13.164 | 1.539 | PostgreSQL |

No Cassandra cada avaliação são 3 escritas (2 tabelas + contador); no PostgreSQL, 1 INSERT com verificação de chaves estrangeiras e atualização de 3 índices.
