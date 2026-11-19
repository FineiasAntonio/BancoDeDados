@echo off
chcp 65001 > nul
title Projeto Banco de Dados - Execucao Completa

:: Garante que o diretorio de trabalho seja o do script
cd /d "%~dp0"

:: Se os arquivos estiverem dentro da subpasta BancoDeDados, entra nela
if exist "BancoDeDados\scripts" (
    cd "BancoDeDados"
)

echo ===============================================================================
echo         PROJETO DE BANCO DE DADOS: RELACIONAL (POSTGRESQL) VS CASSANDRA
echo ===============================================================================
echo Diretorio atual: %CD%
echo.
echo  0. Subir os containers (PostgreSQL e Cassandra) e baixar os dados do MovieLens
echo  1. Criar e popular o banco relacional (PostgreSQL / 3FN)
echo  2. Executar as consultas SQL
echo  3. Criar e popular o Cassandra (tabelas por consulta)
echo  4. Executar as consultas CQL
echo  5. Medir leitura e escrita nos dois bancos (benchmark)
echo.
echo Pressione qualquer tecla para comecar...
pause > nul

echo.
echo -------------------------------------------------------------------------------
echo [ETAPA 0 de 5] Subindo os containers e baixando os dados (se necessario)...
echo -------------------------------------------------------------------------------
docker compose up -d
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Nao foi possivel subir os containers. O Docker Desktop esta aberto?
    pause
    exit /b
)
python scripts/download_data.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha no download dos dados. Verifique sua conexao.
    pause
    exit /b
)

echo.
echo -------------------------------------------------------------------------------
echo [ETAPA 1 de 5] Criando e populando o banco relacional (PostgreSQL / 3FN)...
echo -------------------------------------------------------------------------------
python scripts/load_relational.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha na carga do PostgreSQL.
    pause
    exit /b
)

echo.
echo -------------------------------------------------------------------------------
echo [ETAPA 2 de 5] Executando as consultas SQL...
echo -------------------------------------------------------------------------------
python scripts/test_sql_queries.py

echo.
echo -------------------------------------------------------------------------------
echo [ETAPA 3 de 5] Criando e populando o Cassandra...
echo -------------------------------------------------------------------------------
python scripts/load_cassandra.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha na carga do Cassandra.
    pause
    exit /b
)

echo.
echo -------------------------------------------------------------------------------
echo [ETAPA 4 de 5] Executando as consultas CQL...
echo -------------------------------------------------------------------------------
python scripts/test_cassandra_queries.py

echo.
echo -------------------------------------------------------------------------------
echo [ETAPA 5 de 5] Medindo leitura e escrita nos dois bancos...
echo -------------------------------------------------------------------------------
python scripts/benchmark.py

echo.
echo ===============================================================================
echo                           EXECUCAO CONCLUIDA COM SUCESSO!
echo ===============================================================================
echo.
echo Relatorio:  docs\analise.md
echo Benchmark:  docs\resultados_benchmark.md
echo.
echo Pressione qualquer tecla para fechar esta janela...
pause > nul
