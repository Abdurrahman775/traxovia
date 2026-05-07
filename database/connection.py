"""
database/connection.py — asyncpg pool + FastAPI dependency.

Rule (from CLAUDE.md):
  FastAPI route handlers  → get_db() from this module  (asyncpg, async)
  Celery task functions   → get_sync_db() from sync_connection.py  (psycopg2, sync)
  Never mix the two in the same execution context.

Every connection is wrapped in a transaction so that SET LOCAL variables
(used by RLS policies in rls_policies.sql) are scoped to the request and
automatically cleared when the transaction commits or rolls back.
"""

import asyncpg
from config import settings

_pool: asyncpg.Pool | None = None


async def create_pool() -> None:
    """Call from FastAPI lifespan startup."""
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=5,
        max_size=20,
        command_timeout=30,
    )


async def close_pool() -> None:
    """Call from FastAPI lifespan shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def _get_pool() -> asyncpg.Pool:
    """Lazy-initialise the pool if startup hook was not called (e.g. tests)."""
    global _pool
    if _pool is None:
        await create_pool()
    return _pool


async def get_db():
    """
    FastAPI dependency — yields an asyncpg connection inside a transaction.

    Wrapping in a transaction is required for SET LOCAL to work:
    SET LOCAL only persists for the duration of the enclosing transaction.
    When the transaction commits (normal exit) or rolls back (exception),
    the variable is cleared and the connection is safe to return to the pool.

    Usage in route handlers:
        @router.get("/example")
        async def example(db=Depends(get_db)):
            rows = await db.fetch("SELECT * FROM trades")
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


async def set_rls_user(conn: asyncpg.Connection, user_id: str) -> None:
    """
    Set the per-request RLS context so policies in rls_policies.sql apply.

    Must be called inside an active transaction (i.e. inside a get_db block).
    Call this at the top of any route handler that reads or writes user-owned
    rows (trades, trade_signals, risk_state, feature_store, audit_log).

    Usage:
        async def my_route(user=Depends(get_current_user), db=Depends(get_db)):
            await set_rls_user(db, user["sub"])
            rows = await db.fetch("SELECT * FROM trades")  # RLS now active
    """
    await conn.execute("SELECT set_config('app.current_user_id', $1, true)", user_id)
