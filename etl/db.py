from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def connect():
    return psycopg.connect(autocommit=True, row_factory=dict_row, connect_timeout=10)


def execute_file(connection, filename, parameters=None):
    # Client-side binding permits a file with several SQL statements and typed parameters.
    with psycopg.ClientCursor(connection) as cursor:
        cursor.execute((SQL_DIR / filename).read_text(encoding="utf-8-sig"), parameters)


@contextmanager
def pipeline_lock(connection):
    acquired = connection.execute("SELECT pg_try_advisory_lock(71420261026) AS locked").fetchone()
    if not acquired["locked"]:
        raise RuntimeError("Another pipeline run is active")
    try:
        yield
    finally:
        connection.execute("SELECT pg_advisory_unlock(71420261026)")


def initialize(connection):
    with connection.transaction():
        execute_file(connection, "warehouse.sql")
