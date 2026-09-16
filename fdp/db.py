"""Postgres helpers (psycopg3 + pgvector registration)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Sequence

import psycopg
from pgvector.psycopg import register_vector

from .settings import settings


def connect() -> psycopg.Connection:
    conn = psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=settings.pg_db,
        autocommit=False,
    )
    # pgvector adapter — lets us pass/receive python lists as vector columns.
    try:
        register_vector(conn)
    except Exception:
        # extension may not be created yet on first-ever connect; caller handles.
        pass
    return conn


@contextmanager
def cursor(commit: bool = True):
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql: str, params: Sequence[Any] | None = None) -> None:
    with cursor() as cur:
        cur.execute(sql, params)


def executemany(sql: str, rows: Iterable[Sequence[Any]]) -> None:
    with cursor() as cur:
        cur.executemany(sql, list(rows))


def query(sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
    with cursor(commit=False) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_dicts(sql: str, params: Sequence[Any] | None = None) -> list[dict]:
    with cursor(commit=False) as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def wait_ready(retries: int = 30, delay: float = 2.0) -> bool:
    """Block until Postgres accepts connections (used at container start)."""
    import time

    for _ in range(retries):
        try:
            conn = psycopg.connect(
                host=settings.pg_host, port=settings.pg_port,
                user=settings.pg_user, password=settings.pg_password,
                dbname=settings.pg_db, connect_timeout=3,
            )
            conn.close()
            return True
        except Exception:
            time.sleep(delay)
    return False
