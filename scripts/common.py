"""Funções compartilhadas pelos scripts de ETL, consultas e benchmark."""

import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TITLE_YEAR = re.compile(r"^(.*?)\s*\((\d{4})\)\s*$")

# Endereço padrão do docker-compose.yml (pode ser sobrescrito por variável de ambiente)
CASSANDRA_HOST = os.environ.get("CASSANDRA_HOST", "127.0.0.1")


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


def connect_cassandra(host=CASSANDRA_HOST, keyspace=None, timeout=180):
    """(cluster, session) do Cassandra. O container leva ~1 min para aceitar conexões."""
    from cassandra.cluster import Cluster

    def _open():
        cluster = Cluster([host], connect_timeout=10)
        try:
            return cluster, cluster.connect(keyspace)
        except Exception:
            cluster.shutdown()
            raise

    return _retry(_open, "Cassandra", timeout)


def load_queries(path):
    """Lê um arquivo de consultas dividido por marcadores '-- name: x' ou '// name: x'.

    Cada bloco começa com a linha do marcador, seguida de '-- titulo: ...' (opcional)
    e do texto da consulta. Retorna uma lista de dicts {name, titulo, text}.
    Assim, relational/queries.sql e cassandra/queries.cql são a fonte única das
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
