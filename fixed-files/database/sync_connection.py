"""
database/sync_connection.py  — NEW FILE
CORRECTIONS APPLIED:
  [FIX-4] The original codebase had no synchronous DB helper. Several Celery tasks
          referenced `db_connection()` which was never defined, and others called
          asyncpg async methods inside sync workers (RuntimeError).

          This module provides get_sync_db() — a psycopg2 context manager that
          Celery tasks (retrain, mat-view refresh, trial expiry, SHAP) must use
          instead of asyncpg.

RULE:
  - FastAPI route handlers  → use `from database.connection import get_db`  (asyncpg)
  - Celery task functions   → use `from database.sync_connection import get_sync_db` (psycopg2)
  Never mix the two in the same execution context.
"""

import os
import contextlib
import psycopg2
import psycopg2.extras
from typing import Generator


def _build_dsn() -> str:
    """Build psycopg2 DSN from environment variables."""
    return (
        f"host={os.getenv('DB_HOST', 'localhost')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"dbname={os.getenv('DB_NAME', 'trading_ai')} "
        f"user={os.getenv('DB_USER', 'postgres')} "
        f"password={os.getenv('DB_PASSWORD', '')} "
        f"sslmode={os.getenv('DB_SSLMODE', 'prefer')}"
    )


@contextlib.contextmanager
def get_sync_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Synchronous DB connection for use inside Celery tasks.

    Usage:
        with get_sync_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute('SELECT * FROM trades WHERE id=%s', (trade_id,))
                row = cur.fetchone()
        conn.commit()  # explicit commit for write operations

    The connection is always closed when the context block exits, even on error.
    """
    conn = psycopg2.connect(_build_dsn())
    conn.autocommit = False
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def sync_execute(sql: str, params: tuple = ()) -> None:
    """
    Convenience wrapper for single-statement writes inside Celery tasks.
    Commits automatically.

    Usage:
        sync_execute(
            'UPDATE users SET plan=%s WHERE id=%s',
            ('community', user_id)
        )
    """
    with get_sync_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


def sync_fetchall(sql: str, params: tuple = ()) -> list[dict]:
    """
    Convenience wrapper for SELECT queries that return multiple rows.
    Returns a list of dicts (column-name keyed).

    Usage:
        rows = sync_fetchall(
            'SELECT id, plan FROM users WHERE plan=%s',
            ('trial',)
        )
    """
    with get_sync_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def sync_fetchone(sql: str, params: tuple = ()) -> dict | None:
    """
    Convenience wrapper for SELECT queries that return a single row.
    Returns a dict or None.
    """
    with get_sync_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
