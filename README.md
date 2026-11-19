# Projeto de Banco de Dados: Análise Comparativa Relacional vs. Cassandra

Este repositório contém a implementação, os scripts de ETL, as modelagens e a análise comparativa entre um **SGBD Relacional (PostgreSQL normalizado até a 3FN)** e um **SGBD NoSQL orientado a colunas largas (Apache Cassandra)**, usando a base pública **MovieLens 20M**.

A comparação contrapõe duas formas de modelar: **por entidades** (relacional: tabelas normalizadas, e as consultas se adaptam ao modelo) e **por consultas** (Cassandra: uma tabela para cada pergunta, com os dados duplicados e já ordenados para responder lendo uma única partição). Os tempos de leitura e de escrita são medidos nos dois bancos.

---

## 📁 Estrutura do Projeto

```text
BancoDeDados/
├── data/raw/                       # CSVs do MovieLens (baixados por scripts/download_data.py)
├── relational/
│   ├── postgres_ddl.sql            # DDL do PostgreSQL (3FN, constraints e índices)
│   ├── clean.sql                   # Remove todas as tabelas (para recriar o esquema do zero)
│   └── queries.sql                 # As 6 consultas de comparação em SQL
├── cassandra/
│   ├── schema.cql                  # Keyspace e tabelas, uma por consulta
│   └── queries.cql                 # As 6 consultas equivalentes em CQL
├── scripts/
│   ├── download_data.py            # Baixa e extrai o MovieLens 20M
│   ├── load_relational.py          # ETL: CSVs -> PostgreSQL normalizado (COPY)
│   ├── load_cassandra.py           # ETL: CSVs -> Cassandra (lotes por partição + agregados pré-calculados)
│   ├── test_sql_queries.py         # Executa e exibe as consultas SQL
│   ├── test_cassandra_queries.py   # Executa e exibe as consultas CQL (e a que o Cassandra recusa)
│   ├── benchmark.py                # Mede leitura (6 consultas) e escrita (avaliações/s) nos dois bancos
│   └── common.py                   # Conexões e funções compartilhadas
├── docs/
│   ├── analise.md                  # Relatório técnico completo
│   ├── resultados_benchmark.md     # Gerado por scripts/benchmark.py
│   ├── modelo_logico.puml / .png   # Modelo lógico relacional (PlantUML)
│   └── apresentacao.pptx           # Slides
├── docker-compose.yml              # PostgreSQL 16 e Cassandra 5.0
├── requirements.txt
└── executar_tudo.sh / .bat         # Executa tudo de uma vez (Linux/macOS e Windows)
```

---

## 🚀 Como Executar

### Pré-requisitos

* **Docker** e **Docker Compose** (o Cassandra precisa de ~2 GB de RAM).
* **Python 3.10+**:
  ```bash
  pip install -r requirements.txt
  ```

### Execução automática

```bash
./executar_tudo.sh        # Linux/macOS
executar_tudo.bat         # Windows
```

### Execução passo a passo

```bash
docker compose up -d                 # PostgreSQL (5432) e Cassandra (9042); o Cassandra leva ~1 min para subir
python scripts/download_data.py      # dados em data/raw/

# Relacional
python scripts/load_relational.py --sample-ratings 100000
python scripts/test_sql_queries.py

# Cassandra
python scripts/load_cassandra.py --sample-ratings 100000
python scripts/test_cassandra_queries.py

# Leitura e escrita (gera docs/resultados_benchmark.md)
python scripts/benchmark.py
```

Para carregar os 20 milhões de avaliações, use `--all-ratings` nos dois scripts de carga.

As consultas também podem ser executadas direto nos clientes de cada banco:

```bash
psql -h localhost -U postgres -d movielens -f relational/queries.sql
docker exec -i movielens_cassandra cqlsh < cassandra/queries.cql
```

---

## 🔎 As consultas comparadas

| # | Consulta | No Cassandra |
| :--- | :--- | :--- |
| 1 | Ficha completa de um filme | 2 leituras por chave (filme + contadores) |
| 2 | Top 10 filmes (mínimo de 50 votos) | **Recusada** na forma natural; ranking pré-calculado na carga |
| 3 | Filmes e média por gênero | Pré-calculada na carga |
| 4 | Filmes com as tags `pixar` / `animation` | Tabela própria, tag como chave de partição |
| 5 | Histórico recente de um usuário | Uma partição, já ordenada por data |
| 6 | Avaliações de um filme num período | Faixa dentro de uma partição |
| — | Gravação de avaliações (avaliações/s) | Ponto forte do Cassandra |

---

## 📊 Síntese

| Dimensão | Relacional (PostgreSQL / 3FN) | Cassandra |
| :--- | :--- | :--- |
| **Modelagem** | Por entidades, sem redundância | Por consultas, uma tabela por pergunta |
| **Organização** | 8 tabelas normalizadas | 7 tabelas desnormalizadas |
| **Uma avaliação** | 1 linha em `ratings` | 2 linhas (`ratings_by_user`, `ratings_by_movie`) + contador |
| **Junções** | `JOIN` em qualquer combinação | Não existem |
| **Agregações** | `GROUP BY`, `ORDER BY` livres | Limitadas à partição; o resto é pré-calculado |
| **Integridade** | FK, `CHECK`, tipos | Só tipos; sem chaves estrangeiras |
| **Consistência** | ACID | Ajustável por consulta (`ONE`, `QUORUM`, `ALL`) |
| **Escala** | Vertical (principalmente) | Horizontal, sem nó mestre |

📄 Relatório completo: **[docs/analise.md](docs/analise.md)**
