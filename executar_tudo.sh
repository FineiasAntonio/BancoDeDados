#!/usr/bin/env bash
# Executa o projeto inteiro: sobe os bancos, carrega os dados, roda as consultas e o benchmark.

cd "$(dirname "$0")" || exit 1
if [ -d "BancoDeDados/scripts" ]; then
    cd "BancoDeDados" || exit 1
fi

PY=python3

pausar() {
    read -r -n 1 -s -p "$1" _
    echo
}

etapa() {
    echo
    echo "-------------------------------------------------------------------------------"
    echo "$1"
    echo "-------------------------------------------------------------------------------"
}

falhar() {
    echo "[ERRO] $1"
    pausar "Pressione qualquer tecla para sair..."
    exit 1
}

echo "==============================================================================="
echo "        PROJETO DE BANCO DE DADOS: RELACIONAL (POSTGRESQL) VS GRAFO (NEO4J)"
echo "==============================================================================="
echo "Diretorio atual: $PWD"
echo
echo " 0. Subir os containers (PostgreSQL e Neo4j) e baixar os dados do MovieLens"
echo " 1. Criar e popular o banco relacional (PostgreSQL / 3FN)"
echo " 2. Executar as consultas SQL"
echo " 3. Criar e popular o grafo (Neo4j)"
echo " 4. Executar as consultas Cypher"
echo " 5. Medir o tempo das consultas nos dois bancos (benchmark)"
echo
pausar "Pressione qualquer tecla para comecar..."

etapa "[ETAPA 0 de 5] Subindo os containers e baixando os dados (se necessario)..."
docker compose up -d || falhar "Nao foi possivel subir os containers. O Docker esta rodando?"
"$PY" scripts/download_data.py || falhar "Falha no download dos dados. Verifique sua conexao."

etapa "[ETAPA 1 de 5] Criando e populando o banco relacional (PostgreSQL / 3FN)..."
"$PY" scripts/load_relational.py || falhar "Falha na carga do PostgreSQL."

etapa "[ETAPA 2 de 5] Executando as consultas SQL..."
"$PY" scripts/test_sql_queries.py

etapa "[ETAPA 3 de 5] Criando e populando o grafo (Neo4j)..."
"$PY" scripts/load_neo4j.py || falhar "Falha na carga do Neo4j."

etapa "[ETAPA 4 de 5] Executando as consultas Cypher..."
"$PY" scripts/test_graph_queries.py

etapa "[ETAPA 5 de 5] Medindo o tempo das consultas nos dois bancos..."
"$PY" scripts/benchmark.py

echo
echo "==============================================================================="
echo "                          EXECUCAO CONCLUIDA COM SUCESSO!"
echo "==============================================================================="
echo
echo "Relatorio:  docs/analise.md"
echo "Benchmark:  docs/resultados_benchmark.md"
echo "Grafo:      http://localhost:7474 (usuario neo4j, senha neo4jpassword)"
echo
pausar "Pressione qualquer tecla para fechar esta janela..."
