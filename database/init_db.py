#!/usr/bin/env python3
"""
database/init_db.py — One-shot database initialisation script.

Connects to TimescaleDB and applies the three SQL files in dependency order:
    1. schema.sql            — extensions, application tables, hypertables, indexes
    2. materialized_views.sql — 3 materialized views + unique indexes for CONCURRENT refresh
    3. rls_policies.sql      — roles, per-table RLS, policies, grants

Each file runs inside its own transaction. If a file fails the transaction is
rolled back, a clear diagnostic is printed (file name, PostgreSQL error code,
the exact error message), and the script exits without applying later files.
A verification summary is printed after all three succeed.

Usage
-----
From the project root:
    python -m database.init_db

Or directly:
    python database/init_db.py

Environment
-----------
Reads connection details from .env (or environment variables directly):
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSLMODE
These are the same variables used by database/sync_connection.py.
"""

import os
import sys
import pathlib
import textwrap

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ── Constants ──────────────────────────────────────────────────────────────────

BASE_DIR = pathlib.Path(__file__).parent

# (filename, human label) — applied in this exact order.
STEPS: list[tuple[str, str]] = [
    ("schema.sql",             "core tables · hypertables · indexes"),
    ("materialized_views.sql", "materialized views · unique indexes"),
    ("rls_policies.sql",       "roles · RLS policies · grants"),
]

_HR      = "─" * 64
_HR_THIN = "·" * 64


# ── Connection ─────────────────────────────────────────────────────────────────

def _build_dsn() -> str:
    """Build a psycopg2 DSN from env vars — mirrors sync_connection._build_dsn()."""
    return (
        f"host={os.getenv('DB_HOST', 'localhost')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"dbname={os.getenv('DB_NAME', 'trading_ai')} "
        f"user={os.getenv('DB_USER', 'postgres')} "
        f"password={os.getenv('DB_PASSWORD', '')} "
        f"sslmode={os.getenv('DB_SSLMODE', 'prefer')}"
    )


def _connect() -> psycopg2.extensions.connection:
    """
    Open a psycopg2 connection. Exits with a clear message on failure so the
    operator knows whether the problem is credentials, network, or the DB not
    being up yet.
    """
    dsn = _build_dsn()
    # Print a redacted DSN (no password) so the operator can see what was tried.
    redacted = dsn.replace(os.getenv("DB_PASSWORD", ""), "***") if os.getenv("DB_PASSWORD") else dsn
    print(f"\nConnecting → {redacted}")

    try:
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        print("Connected.\n")
        return conn
    except psycopg2.OperationalError as exc:
        print(_HR, file=sys.stderr)
        print("  ERROR: could not connect to TimescaleDB.", file=sys.stderr)
        print(f"  DSN tried : {redacted}", file=sys.stderr)
        print(f"  Detail    : {exc}", file=sys.stderr)
        print(_HR, file=sys.stderr)
        print("\n  Is TimescaleDB running? Check DB_HOST / DB_PORT in .env.\n",
              file=sys.stderr)
        sys.exit(1)


# ── Already-initialised guard ──────────────────────────────────────────────────

def _check_already_initialised(conn: psycopg2.extensions.connection) -> None:
    """
    Warn (not abort) if the users table already exists. The operator may be
    intentionally re-applying after a partial failure, so this is advisory only.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables"
            "  WHERE table_schema = 'public' AND table_name = 'users'"
            ")"
        )
        exists = cur.fetchone()[0]

    if exists:
        print("  WARNING: the 'users' table already exists.")
        print("  Re-running init_db.py on an initialised database will fail at")
        print("  the first CREATE TABLE statement. If you want a clean slate,")
        print("  drop and recreate the database first:\n")
        print("      docker compose exec db dropdb  -U trading_app trading_ai")
        print("      docker compose exec db createdb -U trading_app trading_ai\n")
        print("  Proceeding anyway — if this is intentional, ignore this warning.\n")


# ── SQL execution ──────────────────────────────────────────────────────────────

def _run_file(
    conn: psycopg2.extensions.connection,
    sql_path: pathlib.Path,
    label: str,
) -> None:
    """
    Read one SQL file and execute its entire content inside a single transaction.
    On success: commit and print a one-line confirmation.
    On failure: rollback, print a full diagnostic, and exit.

    Using a per-file transaction means a partial failure in schema.sql (e.g. a
    typo in table column 5 of 10) leaves no committed state — nothing from that
    file lands in the database, making the error easy to reason about.
    """
    if not sql_path.exists():
        _fatal_missing(sql_path)

    sql = sql_path.read_text(encoding="utf-8")

    print(f"  Applying {sql_path.name:<30}  ({label})")

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"  {'✓':<3} {sql_path.name} — OK\n")

    except psycopg2.Error as exc:
        conn.rollback()
        _print_sql_error(sql_path.name, label, exc)
        sys.exit(1)


def _fatal_missing(sql_path: pathlib.Path) -> None:
    print(_HR, file=sys.stderr)
    print(f"  ERROR: file not found — {sql_path}", file=sys.stderr)
    print(_HR, file=sys.stderr)
    print("\n  Run this script from the project root, e.g.:", file=sys.stderr)
    print("      python -m database.init_db\n", file=sys.stderr)
    sys.exit(1)


def _print_sql_error(
    filename: str,
    label: str,
    exc: psycopg2.Error,
) -> None:
    """Print a structured diagnostic block so the operator knows exactly what failed."""
    print(file=sys.stderr)
    print(_HR, file=sys.stderr)
    print(f"  FAILED  {filename}  ({label})", file=sys.stderr)
    print(_HR, file=sys.stderr)

    # pgcode is the 5-character SQLSTATE (e.g. 42P07 = duplicate table).
    if exc.pgcode:
        print(f"  PG code   : {exc.pgcode}", file=sys.stderr)

    # pgerror is the full server-side message including DETAIL, HINT, CONTEXT.
    if exc.pgerror:
        print(file=sys.stderr)
        for line in exc.pgerror.strip().splitlines():
            print(f"  {line}", file=sys.stderr)
    else:
        print(f"  {exc}", file=sys.stderr)

    # Common causes for each SQLSTATE that appears during init.
    _print_hint(exc.pgcode, filename)

    print(file=sys.stderr)
    print("  Later files were NOT applied (transaction rolled back).", file=sys.stderr)
    print(f"  Fix {filename} then re-run:  python -m database.init_db", file=sys.stderr)
    print(_HR, file=sys.stderr)


def _print_hint(pgcode: str | None, filename: str) -> None:
    """Map common SQLSTATE codes to operator-friendly hints."""
    hints: dict[str, str] = {
        # 42P07 — duplicate table (re-running init on an existing DB)
        "42P07": "A table or view with that name already exists. "
                 "Drop and recreate the database before re-running init_db.",
        # 42710 — duplicate object (role, index, policy already exists)
        "42710": "An object (role, index, or policy) already exists. "
                 "This usually means init_db was already run. "
                 "Drop the database or use IF NOT EXISTS guards.",
        # 58P01 — cannot load shared library (TimescaleDB not installed)
        "58P01": "TimescaleDB shared library could not be loaded. "
                 "Ensure 'timescaledb' appears in postgresql.conf shared_preload_libraries.",
        # 0A000 — feature not supported (e.g. CREATE EXTENSION in wrong context)
        "0A000": "An unsupported feature was used. "
                 "Ensure the DB user has SUPERUSER or CREATEROLE privileges for extension/role creation.",
        # 42501 — insufficient privilege
        "42501": "The DB user lacks the required privilege. "
                 f"The user in DB_USER must have SUPERUSER or CREATEROLE rights to run {filename}.",
        # 3D000 — invalid catalog name (database does not exist)
        "3D000": "The database does not exist. "
                 "Create it first:  createdb -U postgres trading_ai",
        # 28P01 — authentication failure
        "28P01": "Authentication failed. Check DB_USER and DB_PASSWORD in .env.",
        # 08006 — connection failure
        "08006": "Connection failed mid-session. Is the database still running?",
    }
    hint = hints.get(pgcode or "")
    if hint:
        print(file=sys.stderr)
        print(f"  Hint: {textwrap.fill(hint, width=58, subsequent_indent='        ')}",
              file=sys.stderr)


# ── Post-init verification ─────────────────────────────────────────────────────

def _verify(conn: psycopg2.extensions.connection) -> None:
    """
    Query the DB to confirm that hypertables, materialized views, and RLS
    policies were all created correctly. Prints a summary table.
    Exits with code 1 if anything looks wrong.
    """
    print(_HR_THIN)
    print("  VERIFICATION")
    print(_HR_THIN)

    ok = True

    # ── 1. Hypertables ────────────────────────────────────────────────────────
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT hypertable_name "
            "FROM timescaledb_information.hypertables "
            "ORDER BY hypertable_name"
        )
        hypertables = cur.fetchall()

    expected_hypertables = {
        "ohlc_m15":     "1 mon",
        "ohlc_h4":      "6 mons",
        "ohlc_w1":      "2 years",
        "feature_store": "1 mon",
    }

    print(f"\n  {'Hypertables':}")
    if not hypertables:
        print("    ✗  none found — schema.sql may not have applied correctly")
        ok = False
    else:
        for row in hypertables:
            name = row["hypertable_name"]
            print(f"    ✓  {name}")

    # ── 2. Materialized views ─────────────────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "SELECT matviewname FROM pg_matviews "
            "WHERE schemaname = 'public' ORDER BY matviewname"
        )
        views = [r[0] for r in cur.fetchall()]

    expected_views = {"mv_daily_pnl", "mv_rolling_performance", "mv_performance_by_pair"}

    print(f"\n  {'Materialized views':}")
    for v in sorted(expected_views):
        mark = "✓" if v in views else "✗"
        if mark == "✗":
            ok = False
        print(f"    {mark}  {v}")

    # ── 3. RLS-enabled tables ─────────────────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND rowsecurity = TRUE "
            "ORDER BY tablename"
        )
        rls_tables = [r[0] for r in cur.fetchall()]

    expected_rls = {"audit_log", "feature_store", "risk_state", "trade_signals", "trades"}

    print(f"\n  {'RLS enabled':}")
    for t in sorted(expected_rls):
        mark = "✓" if t in rls_tables else "✗"
        if mark == "✗":
            ok = False
        print(f"    {mark}  {t}")

    # ── 4. Table count ────────────────────────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        table_count = cur.fetchone()[0]

    print(f"\n  Total base tables : {table_count}  (expected 13)")
    if table_count != 13:
        ok = False

    # ── Result ────────────────────────────────────────────────────────────────
    print()
    print(_HR)
    if ok:
        print("  Database initialised successfully. All checks passed.")
    else:
        print("  Initialisation completed but some checks FAILED — see ✗ above.",
              file=sys.stderr)
        print("  The database may be in a partial state. Review the output and",
              file=sys.stderr)
        print("  re-run after fixing the issue.", file=sys.stderr)
        sys.exit(1)
    print(_HR)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv()

    print(_HR)
    print("  Trading AI SaaS V3 — database initialisation")
    print(_HR)

    conn = _connect()

    try:
        _check_already_initialised(conn)

        for filename, label in STEPS:
            _run_file(conn, BASE_DIR / filename, label)

        _verify(conn)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
