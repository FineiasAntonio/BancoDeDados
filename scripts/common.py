"""Funções compartilhadas pelos scripts de ETL, consultas e benchmark."""

import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TITLE_YEAR = re.compile(r"^(.*?)\s*\((\d{4})\)\s*$")

# Credenciais padrão do docker-compose.yml (podem ser sobrescritas por variáveis de ambiente)
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4jpassword")


def extract_title_and_year(raw_title):
    """1FN: 'Toy Story (1995)' -> ('Toy Story', 1995). Sem ano -> (título, None)."""
    if not isinstance(raw_title, str):
        return str(raw_title), None
    raw_title = raw_title.strip()
    m = _TITLE_YEAR.match(raw_title)
    return (m.group(1).strip(), int(m.group(2))) if m else (raw_title, None)


def _retry(fn, what, timeout):
    """Tenta conectar por até `timeout` segundos (o container pode estar subindo)."""
    deadline = time.time() + timeout
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if time.time() > deadline:
                raise SystemExit(
                    f"[!] Sem conexão com o {what} ({exc}).\n"
                    f"    Suba os bancos com: docker compose up -d"
                ) from exc
            time.sleep(2)


def connect(host="localhost", port=5432, db="movielens", user="postgres", password=None, timeout=60):
    """Conexão PostgreSQL com os defaults do docker-compose.yml."""
    import psycopg2
    password = password or os.environ.get("PGPASSWORD", "postgrespassword")
    return _retry(lambda: psycopg2.connect(host=host, port=port, dbname=db, user=user,
                                           password=password),
                  "PostgreSQL", timeout)


def connect_neo4j(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD, timeout=90):
    """Driver Neo4j já com a conectividade verificada."""
    from neo4j import GraphDatabase

    def _open():
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
        except Exception:
            driver.close()
            raise
        return driver

    return _retry(_open, "Neo4j", timeout)


def load_queries(path):
    """Lê um arquivo de consultas dividido por marcadores '-- name: x' ou '// name: x'.

    Cada bloco começa com a linha do marcador, seguida de '-- titulo: ...' (opcional)
    e do texto da consulta. Retorna uma lista de dicts {name, titulo, text}.
    Assim, relational/queries.sql e neo4j/queries.cypher são a fonte única das
    consultas usadas pelo relatório, pelos scripts de teste e pelo benchmark.
    """
    marker = re.compile(r"^\s*(?:--|//)\s*name:\s*(\S+)\s*$")
    title = re.compile(r"^\s*(?:--|//)\s*titulo:\s*(.+?)\s*$")
    queries, current = [], None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = marker.match(line)
        if m:
            current = {"name": m.group(1), "titulo": "", "lines": []}
            queries.append(current)
            continue
        if current is None:
            continue
        t = title.match(line)
        if t and not current["titulo"]:
            current["titulo"] = t.group(1)
            continue
        current["lines"].append(line)
    for q in queries:
        lines = q.pop("lines")
        # descarta comentários/linhas vazias que sobram no fim do bloco (separadores visuais)
        while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith(("--", "//"))):
            lines.pop()
        q["text"] = "\n".join(lines).strip().rstrip(";").strip()
    return queries
