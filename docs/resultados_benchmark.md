# Resultados do Benchmark: PostgreSQL vs. Cassandra

- Data: 2026-11-19 16:11
- Máquina: Linux x86_64, Python 3.13.18
- Avaliações carregadas: 20.000.263
- Leitura: 1 aquecimento + média de 10 execuções (ms).

| Consulta | PostgreSQL (ms) | Cassandra (ms) | Mais rápido |
| :--- | ---: | ---: | :---: |
| Consulta 1 - Ficha completa de um filme (Toy Story) | 52,7 | 2,2 | Cassandra |
| Consulta 2 - Top 10 filmes mais bem avaliados (mínimo de 50 votos) | 2.737,5 | 1,5 | Cassandra |
| Consulta 3 - Total de filmes e média das avaliações por gênero | 50.978,4 | 1,1 | Cassandra |
| Consulta 4 - Filmes marcados com 'pixar' ou 'animation' | 4,5 | 2,1 | Cassandra |
| Consulta 5 - Histórico recente do usuário 42 (últimas 20 avaliações) | 0,1 | 1,0 | PostgreSQL |
| Consulta 6 - Avaliações de Toy Story em janeiro de 2015 | 0,5 | 1,6 | PostgreSQL |

## Escrita: 100.000 avaliações novas, gravadas uma a uma

| Processos × escritas simultâneas | PostgreSQL (avaliações/s) | Cassandra (avaliações/s) | Mais rápido |
| ---: | ---: | ---: | :---: |
| 2 × 16 | 14.600 | 3.142 | PostgreSQL |

No Cassandra cada avaliação são 3 escritas (2 tabelas + contador); no PostgreSQL, 1 INSERT com verificação de chaves estrangeiras e atualização de 3 índices.
