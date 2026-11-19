# Análise Comparativa: Banco de Dados Relacional (PostgreSQL) vs. Colunas Largas (Apache Cassandra)

**Dataset analisado:** MovieLens 20M (GroupLens Research)  
**Contexto:** estudo comparativo entre os paradigmas **Relacional (3FN)** e **NoSQL de colunas largas (wide-column)**.

---

## 1. Introdução e Contextualização do Problema

O objetivo deste estudo é modelar, implementar e confrontar duas abordagens de gerenciamento de dados sobre a mesma base pública: o dataset **MovieLens 20M**, com cadastro de filmes (`movie.csv`), links externos (`link.csv`), tags atribuídas por usuários (`tag.csv`) e **mais de 20 milhões de avaliações** (`rating.csv`).

As 20 milhões de avaliações são o centro da escolha do Cassandra como contraponto: é um volume grande, que só cresce (cada nota é uma inserção), e que é quase sempre lido por uma chave conhecida — "as avaliações deste usuário", "as avaliações deste filme". É exatamente o tipo de carga para o qual o Cassandra foi projetado.

1. **Paradigma Relacional**: modelagem **por entidades**. Os dados são normalizados (1FN a 3FN), sem redundância, com integridade garantida por chaves e transações ACID. Qualquer pergunta é respondida combinando tabelas com `JOIN`, `GROUP BY` e `ORDER BY`.
2. **Paradigma de colunas largas (Cassandra)**: modelagem **por consultas**. Parte-se da lista de perguntas e cria-se **uma tabela para cada uma**, com os dados duplicados e já ordenados no disco de forma que cada resposta seja a leitura de uma única partição. Não há `JOIN`, e agregações só funcionam dentro de uma partição. Em troca, o banco escala horizontalmente, sem nó mestre, e aceita escritas em altíssimo volume.

---

## 2. Modelagem e Estrutura de Dados

### 2.1. Abordagem Relacional (PostgreSQL - 3FN)

A base bruta foi normalizada da seguinte forma:

* **1ª Forma Normal (1FN)** — todo atributo deve ser atômico:
  * O atributo multivalorado `genres` (ex.: `"Action|Adventure|Sci-Fi"`) foi decomposto na tabela catálogo `genres` e na associativa $N:M$ `movie_genres`.
  * O título composto `"Toy Story (1995)"` foi separado em `title` e `release_year`.
* **2ª Forma Normal (2FN)** — nenhum atributo não-chave pode depender de **parte** de uma chave composta. Em `ratings`, a chave é `(user_id, movie_id)` e tanto `rating` quanto `rated_at` dependem do par completo (a nota é *de um usuário para um filme*). Não há dependência parcial: a tabela já está em 2FN. O mesmo vale para `movie_genres` e `user_movie_tags`.
* **3ª Forma Normal (3FN)** — nenhum atributo não-chave pode depender de outro atributo não-chave. Em `movies`, `title` e `release_year` dependem apenas de `movie_id`; em `movie_links`, `imdb_id` e `tmdb_id` também. Não há dependências transitivas no modelo.

Duas decisões **de projeto** (que vão além do exigido pela 3FN) merecem registro:

* **Catálogo de tags** (`tags` + `user_movie_tags`): o texto da tag não depende transitivamente de nada — ele é o próprio dado. Separá-lo num catálogo com chave substituta (`tag_id`) é uma escolha para **evitar repetir a mesma string** em centenas de milhares de linhas e padronizar a grafia (minúsculas, sem espaços nas pontas).
* **Links externos em tabela 1:1** (`movie_links`): também não é exigência da 3FN (os IDs dependem diretamente de `movie_id`). A separação isola metadados de fontes externas que nem todo filme possui (`tmdb_id` ausente em alguns casos).

```mermaid
erDiagram
    USERS ||--o{ RATINGS : "avalia"
    MOVIES ||--o{ RATINGS : "recebe"
    USERS ||--o{ USER_MOVIE_TAGS : "atribui"
    MOVIES ||--o{ USER_MOVIE_TAGS : "recebe"
    TAGS ||--o{ USER_MOVIE_TAGS : "categoriza"
    MOVIES ||--o{ MOVIE_GENRES : "possui"
    GENRES ||--o{ MOVIE_GENRES : "classifica"
    MOVIES ||--o| MOVIE_LINKS : "links_ext"

    MOVIES {
        int movie_id PK
        varchar title
        smallint release_year
    }
    GENRES {
        int genre_id PK
        varchar name UK
    }
    MOVIE_GENRES {
        int movie_id PK, FK
        int genre_id PK, FK
    }
    MOVIE_LINKS {
        int movie_id PK, FK
        varchar imdb_id
        int tmdb_id
    }
    TAGS {
        int tag_id PK
        varchar tag_name UK
    }
    USER_MOVIE_TAGS {
        int user_id PK, FK
        int movie_id PK, FK
        int tag_id PK, FK
        timestamp tagged_at PK
    }
    RATINGS {
        int user_id PK, FK
        int movie_id PK, FK
        numeric rating
        timestamp rated_at
    }
    USERS {
        int user_id PK
    }
```

> O diagrama editável está em [`der.drawio`](der.drawio) e o modelo lógico em [`modelo_logico.puml`](modelo_logico.puml).

* **Resultado relacional**: **8 tabelas**.

Para as consultas por usuário e por filme ordenadas por data (consultas 5 e 6), a tabela `ratings` tem os índices `(user_id, rated_at)` e `(movie_id, rated_at)`. Assim o PostgreSQL também responde a essas perguntas lendo o índice já na ordem certa — uma comparação justa com as tabelas do Cassandra, que são desenhadas para elas.

---

### 2.2. Abordagem em Colunas Largas (Cassandra)

No Cassandra, cada tabela tem uma **chave de partição** (define em qual nó e em qual bloco do disco a linha mora) e **colunas de ordenação** (*clustering columns*, que definem a ordem das linhas dentro da partição). Uma consulta eficiente lê **uma** partição, de preferência uma faixa contínua dela.

| Tabela | Chave de partição | Ordenação | Responde à |
| :--- | :--- | :--- | :--- |
| `movies` | `movie_id` | — | Consulta 1: ficha do filme (gêneros e tags como `set<text>` na própria linha) |
| `movie_stats` | `movie_id` | — | Consulta 1: total e soma das notas (contadores) |
| `top_movies` | `bucket` | `avg_rating DESC, vote_count DESC, movie_id` | Consulta 2: ranking pré-calculado |
| `genre_stats` | `genre` | — | Consulta 3: agregados por gênero pré-calculados |
| `movies_by_tag` | `tag` | `movie_id` | Consulta 4: filmes de uma tag |
| `ratings_by_user` | `user_id` | `rated_at DESC, movie_id` | Consulta 5: histórico do usuário |
| `ratings_by_movie` | `movie_id` | `rated_at DESC, user_id` | Consulta 6: avaliações do filme por período |

```sql
CREATE TABLE movielens.ratings_by_user (
    user_id  int,
    rated_at timestamp,
    movie_id int,
    rating   float,
    PRIMARY KEY ((user_id), rated_at, movie_id)
) WITH CLUSTERING ORDER BY (rated_at DESC, movie_id ASC);
```

Decisões de modelagem:

* **Desnormalização deliberada**: cada avaliação é gravada **duas vezes** (`ratings_by_user` e `ratings_by_movie`) e ainda soma nos contadores de `movie_stats`. O título do filme é repetido em `movies_by_tag` e `top_movies`. No relacional isso seria uma anomalia; no Cassandra é o modelo.
* **O que o banco não sabe agregar é calculado na carga**: o top 10 e as médias por gênero exigiriam `GROUP BY` sobre toda a base com `ORDER BY` pelo resultado, o que o Cassandra não permite. O script de carga calcula esses números e grava em `top_movies` e `genre_stats`. O custo: esses valores ficam desatualizados até a próxima recarga (ou exigem um processo à parte para mantê-los).
* **Contadores em meias estrelas**: colunas `counter` só aceitam inteiros. A soma das notas é guardada como `nota × 2` (`half_stars_sum`), e a média é calculada na aplicação.
* **Gêneros e tags como coleções** (`set<text>`) dentro da linha do filme, no lugar das tabelas associativas `movie_genres` e `user_movie_tags`.
* **Sem integridade referencial**: nada impede uma avaliação de um filme que não existe. Essa garantia passa para a aplicação.
* **Um único nó** (fator de replicação 1). Em produção, o padrão seria `NetworkTopologyStrategy` com 3 réplicas por data center.

* **Resultado Cassandra**: **7 tabelas**, cada uma servindo uma consulta.

---

## 3. Processo de ETL

1. **Extração** (`download_data.py`): baixa o `ml-20m.zip` e extrai os quatro CSVs.
2. **Transformação** (pandas, as mesmas regras para os dois bancos): título e ano separados, gêneros explodidos, tags normalizadas (sem espaços nas pontas, minúsculas), timestamp Unix convertido para data e hora, IMDb com zeros à esquerda.
3. **Carga**:
   * **PostgreSQL** (`load_relational.py`): `COPY` em lotes de 500 mil linhas, na ordem que respeita as chaves estrangeiras.
   * **Cassandra** (`load_cassandra.py`): escritas assíncronas e em paralelo pelo driver, agrupadas em lotes `UNLOGGED BATCH` **da mesma partição** (até 100 linhas). Lotes de uma partição só vão para um nó e são gravados de uma vez; lotes que misturam partições são um antipadrão no Cassandra. Ao final, a carga grava os contadores, o top 10 e os agregados por gênero.

Agrupar por partição deixou a carga **8 vezes mais rápida** do que gravar linha a linha (de ~2.200 para ~17.500 avaliações por segundo).

---

## 4. Confronto Direto de Consultas (SQL vs. CQL)

As consultas estão em [`relational/queries.sql`](../relational/queries.sql) e [`cassandra/queries.cql`](../cassandra/queries.cql).

### Consulta 1: Ficha completa de um filme

```sql
SELECT m.movie_id, m.title, m.release_year, l.imdb_id, l.tmdb_id,
       (SELECT string_agg(g.name, ', ' ORDER BY g.name)
          FROM movie_genres mg JOIN genres g ON g.genre_id = mg.genre_id
         WHERE mg.movie_id = m.movie_id) AS genres,
       r.total_ratings, r.avg_rating
FROM movies m
LEFT JOIN movie_links l ON l.movie_id = m.movie_id
CROSS JOIN LATERAL (
    SELECT COUNT(*) AS total_ratings, ROUND(AVG(rating), 2) AS avg_rating
      FROM ratings WHERE movie_id = m.movie_id
) r
WHERE m.movie_id = 1;
```

```sql
SELECT movie_id, title, release_year, imdb_id, tmdb_id, genres
FROM movielens.movies WHERE movie_id = 1;
SELECT half_stars_sum, rating_count
FROM movielens.movie_stats WHERE movie_id = 1;
```

* No PostgreSQL, a média é calculada na hora, lendo as dezenas de milhares de avaliações de Toy Story. No Cassandra são **duas leituras por chave**; a média vem dos contadores, mantidos a cada escrita.

### Consulta 2: Top 10 filmes (mínimo de 50 votos)

```sql
SELECT m.movie_id, m.title, m.release_year,
       COUNT(*) AS vote_count, ROUND(AVG(r.rating), 3) AS average_rating
FROM movies m
JOIN ratings r ON r.movie_id = m.movie_id
GROUP BY m.movie_id, m.title, m.release_year
HAVING COUNT(*) >= 50
ORDER BY AVG(r.rating) DESC, vote_count DESC, m.movie_id
LIMIT 10;
```

No Cassandra, essa consulta **não pode ser feita na hora**:

```sql
SELECT movie_id, avg(rating) FROM movielens.ratings_by_movie
GROUP BY movie_id ORDER BY avg(rating) DESC LIMIT 10;
-- erro de sintaxe: ORDER BY não aceita agregações, só colunas de ordenação

SELECT movie_id, avg(rating) FROM movielens.ratings_by_movie
GROUP BY movie_id ORDER BY rated_at DESC LIMIT 10;
-- InvalidRequest: ORDER BY is only supported when the partition key is restricted by an EQ or an IN.
```

O `ORDER BY` do CQL só ordena linhas **dentro de uma partição**, e só pelas colunas de ordenação. Não existe ordenar pelo resultado de uma agregação.

O que funciona é ler o ranking pré-calculado:

```sql
SELECT movie_id, title, release_year, vote_count, avg_rating
FROM movielens.top_movies WHERE bucket = 'all' LIMIT 10;
```

* É a consulta que melhor mostra o limite do Cassandra: ele não faz análise livre sobre a base. Toda pergunta de BI precisa ser prevista e pré-calculada.
* A partição única `bucket = 'all'` concentra a leitura num só nó (*hot partition*). Com milhares de linhas não é problema; em escala maior, o ranking seria dividido em vários buckets.

### Consulta 3: Filmes e média das avaliações por gênero

```sql
SELECT g.name AS genre, COUNT(DISTINCT mg.movie_id) AS total_movies,
       COUNT(r.rating) AS total_ratings, ROUND(AVG(r.rating), 2) AS avg_genre_rating
FROM genres g
JOIN movie_genres mg ON mg.genre_id = g.genre_id
LEFT JOIN ratings r  ON r.movie_id = mg.movie_id
GROUP BY g.genre_id, g.name
ORDER BY total_movies DESC, genre;
```

```sql
SELECT genre, total_movies, total_ratings, avg_rating
FROM movielens.genre_stats;   -- a aplicação ordena por total_movies
```

* Mesma situação da Consulta 2: o Cassandra só lê o resultado pronto. A ordenação fica com a aplicação, porque a tabela tem uma partição por gênero e não há ordenação entre partições.

### Consulta 4: Filmes marcados com `pixar` ou `animation`

```sql
SELECT m.movie_id, m.title, m.release_year, string_agg(DISTINCT t.tag_name, ', ') AS matched_tags
FROM movies m
JOIN user_movie_tags umt ON umt.movie_id = m.movie_id
JOIN tags t              ON t.tag_id = umt.tag_id
WHERE t.tag_name IN ('pixar', 'animation')
GROUP BY m.movie_id, m.title, m.release_year
ORDER BY m.movie_id LIMIT 20;
```

```sql
SELECT tag, movie_id, title, release_year
FROM movielens.movies_by_tag WHERE tag IN ('pixar', 'animation');
```

* O `IN` é permitido porque `tag` é a chave de partição: são lidas exatamente duas partições. O título está duplicado na tabela para evitar uma segunda leitura.

### Consulta 5: Histórico recente de um usuário

```sql
SELECT r.movie_id, r.rating, r.rated_at
FROM ratings r
WHERE r.user_id = 42
ORDER BY r.rated_at DESC, r.movie_id
LIMIT 20;
```

```sql
SELECT movie_id, rating, rated_at
FROM movielens.ratings_by_user WHERE user_id = 42 LIMIT 20;
```

* No Cassandra, as avaliações do usuário estão juntas no disco, já do mais recente para o mais antigo: a consulta lê as primeiras 20 linhas de uma partição e para.

### Consulta 6: Avaliações de Toy Story em janeiro de 2015

```sql
SELECT r.user_id, r.rating, r.rated_at
FROM ratings r
WHERE r.movie_id = 1
  AND r.rated_at >= '2015-01-01' AND r.rated_at < '2015-02-01'
ORDER BY r.rated_at DESC, r.user_id;
```

```sql
SELECT user_id, rating, rated_at
FROM movielens.ratings_by_movie
WHERE movie_id = 1
  AND rated_at >= '2015-01-01 00:00:00+0000'
  AND rated_at <  '2015-02-01 00:00:00+0000';
```

* Faixa contínua dentro da partição do filme. Filtrar por qualquer coluna que não seja da chave (por exemplo, `rating = 5`) é recusado ("Cannot execute this query as it might involve data filtering..."), a não ser com `ALLOW FILTERING`, que lê a partição inteira e é desaconselhado.

---

## 5. Resultados do Benchmark

Medidos com [`scripts/benchmark.py`](../scripts/benchmark.py) na **base completa** (20.000.263 avaliações), PostgreSQL 16 e Cassandra 5.0 num único servidor (4 núcleos, 15 GB de RAM). Todos os resultados foram conferidos: as seis consultas devolvem exatamente os mesmos dados nos dois bancos. Tabela completa em [`resultados_benchmark.md`](resultados_benchmark.md).

### 5.1. Carga

| | PostgreSQL | Cassandra |
| :--- | ---: | ---: |
| Tempo de carga (20 milhões de avaliações) | 7 min | 17 min |
| Linhas de avaliação gravadas | 20 milhões | 40 milhões (2 tabelas) |

A carga do PostgreSQL usa `COPY`, a importação em massa nativa. A do Cassandra usa o driver Python com lotes por partição; o equivalente ao `COPY` seria uma ferramenta de carga em massa (DSBulk ou geração direta de SSTables), não testada.

### 5.2. Leitura (tempo médio de 10 execuções)

| Consulta | PostgreSQL | Cassandra |
| :--- | ---: | ---: |
| 1 · Ficha do filme | 52,7 ms | 2,2 ms |
| 2 · Top 10 | 2.737,5 ms | 1,5 ms |
| 3 · Por gênero | 50.978,4 ms | 1,1 ms |
| 4 · Busca por tags | 4,5 ms | 2,1 ms |
| 5 · Histórico do usuário | 0,1 ms | 1,0 ms |
| 6 · Período de um filme | 0,5 ms | 1,6 ms |

* **Consultas 1 a 3**: a vantagem do Cassandra vem do **pré-cálculo** feito na carga (contadores, ranking e agregados por gênero). O PostgreSQL calcula tudo na hora sobre 20 milhões de linhas. É uma comparação entre "calcular" e "ler pronto": o PostgreSQL com uma *materialized view* também responderia em milissegundos, com o mesmo problema de manter os valores atualizados.
* **Consulta 4**: os dois em poucos milissegundos; o Cassandra lê duas partições, o PostgreSQL faz duas junções indexadas e um agrupamento.
* **Consultas 5 e 6**: com os índices compostos certos, o PostgreSQL é **mais rápido**. Os dois leem os dados já na ordem do índice ou da partição; a diferença de ~1 ms é o custo fixo de cada requisição no Cassandra (protocolo e driver).

### 5.3. Escrita (100 mil avaliações novas, gravadas uma a uma, 2 processos × 16 simultâneas)

| | PostgreSQL | Cassandra |
| :--- | ---: | ---: |
| Avaliações por segundo | **14.600** | 3.142 |
| Escritas por avaliação | 1 `INSERT` | 2 `INSERT` + 1 contador |

* **Neste ambiente, o PostgreSQL gravou ~4,6 vezes mais rápido.** Por operação individual, a diferença cai para ~1,5 vez (3.142 × 3 = ~9.400 operações por segundo no Cassandra).
* **Por que o Cassandra não venceu**:
  1. **Desnormalização**: cada avaliação custa três escritas, uma delas num contador, que é a operação mais cara do Cassandra (lê o valor atual antes de gravar).
  2. **Cliente**: um processo Python com o driver do Cassandra satura em ~6 mil operações por segundo; com 4 núcleos compartilhados entre clientes e servidor, não houve como gerar mais carga.
  3. **Um único nó**: a vantagem de escrita do Cassandra é **escalar horizontalmente** — acrescentar nós aumenta a capacidade quase linearmente, sem nó mestre. Num servidor só, essa vantagem não existe.
* Antes de chegar a esse método, a primeira tentativa foi descartada: com um único processo cliente, o Cassandra ficou em ~1.700 avaliações por segundo, limitado pelo Python e não pelo banco.

---

## 6. Análise Comparativa Detalhada

### 6.1. Esquema, Flexibilidade e Integridade

| Critério | Relacional (PostgreSQL) | Cassandra |
| :--- | :--- | :--- |
| **Ponto de partida** | As entidades e suas dependências funcionais. | A lista de consultas. |
| **Redundância** | Nenhuma (3FN). | Deliberada: a mesma avaliação em duas tabelas, títulos repetidos. |
| **Consulta nova** | Normalmente só um `SELECT` novo (talvez um índice). | Normalmente uma **tabela nova** e uma recarga dos dados. |
| **Integridade referencial** | Garantida pelo banco (`FOREIGN KEY`, `CHECK`). | Inexistente: fica com a aplicação. |
| **Junções e agregações** | Livres. | Sem `JOIN`; `GROUP BY`/`ORDER BY` só dentro da partição. |
| **Consistência entre cópias** | Não se aplica (uma cópia). | Responsabilidade da aplicação: se uma das duas escritas falhar, as tabelas divergem. |

### 6.2. Transações e Consistência

* **PostgreSQL**: ACID. Registrar uma avaliação e atualizar qualquer agregado acontece numa transação: ou tudo, ou nada.
* **Cassandra**: atomicidade e isolamento apenas **dentro de uma partição**. Gravar a avaliação em `ratings_by_user` e em `ratings_by_movie` são escritas em partições diferentes; um `BATCH LOGGED` garante que as duas acabam acontecendo, mas sem isolamento (um leitor pode ver uma e não a outra por alguns instantes). Contadores não entram em lotes com outras tabelas e **não são idempotentes**: se uma atualização for repetida após um timeout, a contagem fica errada.
* **Consistência ajustável**: cada operação escolhe quantas réplicas precisam confirmar (`ONE`, `QUORUM`, `ALL`). Com 3 réplicas, gravar e ler com `QUORUM` (2 + 2 > 3) garante ler o dado mais recente; ler com `ONE` é mais rápido, mas pode devolver um valor antigo. Neste projeto, com um único nó, todos os níveis se comportam igual — a demonstração exigiria um cluster de 3 nós.
* **Teorema CAP**: o Cassandra prioriza **disponibilidade e tolerância a partição (AP)**, com consistência ajustável por operação. O PostgreSQL, com um servidor principal, prioriza consistência.

### 6.3. Desempenho e Escala

1. **Leitura por chave**: os dois bancos respondem em milissegundos quando a consulta encontra um índice (PostgreSQL) ou uma partição (Cassandra). No PostgreSQL, com o índice certo, as consultas 5 e 6 chegam a ser mais rápidas.
2. **Agregações**: o PostgreSQL calcula na hora, o que leva segundos sobre 20 milhões de linhas. O Cassandra **não calcula**: lê o resultado pronto. O tempo baixo das consultas 2 e 3 no Cassandra vem do **pré-cálculo**, não do banco. Uma *materialized view* no PostgreSQL faria o mesmo, com o mesmo custo de manutenção.
3. **Escrita**: o caminho de escrita do Cassandra (log de commit + memória, sem leitura antes de gravar, sem verificação de chaves estrangeiras) é barato **por nó**, e a capacidade total cresce acrescentando nós. Neste projeto, com **um nó e quatro núcleos**, isso não aparece: cada avaliação são 3 escritas no Cassandra contra 1 no PostgreSQL, e o cliente Python precisa de mais processamento para cada requisição.
4. **Escalabilidade**: o Cassandra distribui as partições entre os nós por hash da chave, sem nó mestre; dobrar o número de nós dobra, aproximadamente, a capacidade de leitura e escrita. O PostgreSQL escala principalmente verticalmente, com réplicas de leitura; dividir a escrita entre servidores exige soluções externas (por exemplo, Citus).

---

## 7. Matriz Síntese de Decisão

| Dimensão | Relacional (PostgreSQL) | Cassandra |
| :--- | :--- | :--- |
| Modelagem | Por entidades (normalização) | Por consultas (desnormalização) |
| Linguagem | SQL completo | CQL: parece SQL, sem JOIN e com filtros só pela chave |
| Perguntas novas | Fáceis | Exigem nova tabela e recarga |
| Agregações sobre a base | **Fortes** | Inexistentes (pré-calculadas) |
| Leitura por chave | Rápida com índice | Rápida por desenho |
| Escrita num nó | Mais rápida neste teste | Mais lenta neste teste (3 escritas por avaliação) |
| Escrita em escala | Limitada ao servidor principal | **Cresce com o número de nós** |
| Integridade | FK, `CHECK`, tipos | Só tipos |
| Consistência | ACID | Ajustável por operação (AP) |
| Caso de uso no MovieLens | Catálogo, relatórios, BI | Fluxo de avaliações, históricos por usuário e por filme |

---

## 8. Conclusão e Recomendações

1. **Quando adotar o modelo relacional (PostgreSQL)**:
   * Quando as perguntas mudam e não são conhecidas de antemão (BI, relatórios, análises).
   * Quando há agregações sobre grandes volumes.
   * Quando a integridade (chaves estrangeiras, domínios) e as transações são obrigatórias.

2. **Quando adotar o Cassandra**:
   * Quando o volume de escrita é grande e contínuo (eventos, avaliações, sensores, logs) e precisa crescer além de um servidor.
   * Quando as consultas são conhecidas e sempre por uma chave (o histórico de um usuário, as avaliações de um filme num período).
   * Quando disponibilidade importa mais do que consistência imediata (um nó caído não pode derrubar o serviço).

3. **Arquitetura recomendada (persistência poliglota)**: numa plataforma real inspirada no MovieLens:
   * **PostgreSQL** como fonte da verdade do catálogo, dos usuários e dos relatórios.
   * **Cassandra** recebendo o fluxo de avaliações e servindo as telas por chave (histórico, avaliações recentes), com os agregados recalculados periodicamente a partir dele.
