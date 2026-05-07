"""
database/migrate.py — Idempotent migrations that run on every app startup.
All statements use IF NOT EXISTS / ON CONFLICT DO NOTHING so they are safe
to run multiple times.
"""
import logging
from database.connection import _get_pool

logger = logging.getLogger(__name__)

# Each item is a (description, sql) pair.
# Statements must be idempotent (IF NOT EXISTS, ON CONFLICT DO NOTHING, etc.)
MIGRATIONS = [
    # ── Profile columns ──────────────────────────────────────────────────────
    (
        "add display_name and avatar_url to users",
        """
        ALTER TABLE users
          ADD COLUMN IF NOT EXISTS display_name VARCHAR(80),
          ADD COLUMN IF NOT EXISTS avatar_url   TEXT
        """,
    ),
    # ── Settings columns ─────────────────────────────────────────────────────
    (
        "add extended settings columns to users",
        """
        ALTER TABLE users
          ADD COLUMN IF NOT EXISTS trading_mode          VARCHAR(20)  DEFAULT 'signal_approval',
          ADD COLUMN IF NOT EXISTS news_blocking         BOOLEAN      DEFAULT TRUE,
          ADD COLUMN IF NOT EXISTS friday_cutoff         BOOLEAN      DEFAULT TRUE,
          ADD COLUMN IF NOT EXISTS risk_max_pct          NUMERIC(5,2) DEFAULT 2.0,
          ADD COLUMN IF NOT EXISTS risk_max_drawdown_pct NUMERIC(5,2) DEFAULT 15.0,
          ADD COLUMN IF NOT EXISTS risk_daily_pct        NUMERIC(5,2) DEFAULT 5.0,
          ADD COLUMN IF NOT EXISTS active_pairs          JSONB        DEFAULT '{"EUR/USD":true,"GBP/USD":true,"USD/JPY":false,"AUD/USD":false,"XAU/USD":false}',
          ADD COLUMN IF NOT EXISTS mt5_accounts          JSONB        DEFAULT '[]'
        """,
    ),
    # ── Plan config table ────────────────────────────────────────────────────
    (
        "create plan_config table",
        """
        CREATE TABLE IF NOT EXISTS plan_config (
          plan_id    VARCHAR(20)  PRIMARY KEY,
          name       VARCHAR(50)  NOT NULL,
          price      NUMERIC(8,2) NOT NULL DEFAULT 0,
          color      VARCHAR(20)  NOT NULL DEFAULT '#8899b4',
          popular    BOOLEAN      NOT NULL DEFAULT FALSE,
          sort_order INT          NOT NULL DEFAULT 0,
          is_active  BOOLEAN      NOT NULL DEFAULT TRUE,
          features   JSONB        NOT NULL DEFAULT '{}',
          updated_at TIMESTAMPTZ  DEFAULT NOW()
        )
        """,
    ),
    # ── Bot / Telegram config ────────────────────────────────────────────────
    (
        "create bot_config table",
        """
        CREATE TABLE IF NOT EXISTS bot_config (
          id                         INTEGER      PRIMARY KEY DEFAULT 1,
          telegram_bot_token         TEXT         NOT NULL DEFAULT '',
          telegram_signals_channel   TEXT         NOT NULL DEFAULT '',
          telegram_community_channel TEXT         NOT NULL DEFAULT '',
          telegram_admin_chat_id     TEXT         NOT NULL DEFAULT '',
          signals_drop_enabled       BOOLEAN      NOT NULL DEFAULT TRUE,
          results_drop_enabled       BOOLEAN      NOT NULL DEFAULT TRUE,
          notify_on_approve          BOOLEAN      NOT NULL DEFAULT TRUE,
          notify_on_reject           BOOLEAN      NOT NULL DEFAULT FALSE,
          bridge_alerts_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
          updated_at                 TIMESTAMPTZ  DEFAULT NOW(),
          CONSTRAINT bot_config_singleton CHECK (id = 1)
        )
        """,
    ),
    (
        "seed bot_config singleton row",
        "INSERT INTO bot_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
    ),
    # ── Branding columns on bot_config ──────────────────────────────────────
    (
        "add app_name and app_logo_url to bot_config",
        """
        ALTER TABLE bot_config
          ADD COLUMN IF NOT EXISTS app_name     TEXT NOT NULL DEFAULT 'Trading AI',
          ADD COLUMN IF NOT EXISTS app_logo_url TEXT NOT NULL DEFAULT ''
        """,
    ),
    # ── Cache bot username to avoid per-request Telegram API calls ──────────
    (
        "add telegram_bot_username cache column to bot_config",
        """
        ALTER TABLE bot_config
          ADD COLUMN IF NOT EXISTS telegram_bot_username TEXT NOT NULL DEFAULT ''
        """,
    ),
    # ── Ensure is_admin column exists (may already be in base schema) ────────
    (
        "ensure is_admin column on users",
        """
        ALTER TABLE users
          ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE
        """,
    ),
    # ── Sync is_admin flag for all elite plan users ──────────────────────────
    (
        "set is_admin=true for elite plan users",
        "UPDATE users SET is_admin = TRUE WHERE plan = 'elite' AND is_admin = FALSE",
    ),
    # ── Elite plan — full unlimited access ──────────────────────────────────
    (
        "update elite plan to unlimited features",
        """
        INSERT INTO plan_config (plan_id, name, price, color, popular, sort_order, features)
        VALUES (
          'elite', 'Elite', 299, '#8b5cf6', false, 4,
          '{"pairs":999,"mt5_accounts":99,"dashboard":true,"signals_web":true,
            "signals_tg_drops":true,"tg_bot_approve":true,"tg_bot_settings":true,
            "auto_execute":true,"copy_trade":true,"api_access":true,
            "mobile_app":true,"priority_support":true}'
        )
        ON CONFLICT (plan_id) DO UPDATE SET
          features = EXCLUDED.features
        """,
    ),
    # ── User notification prefs + copy trade flag ────────────────────────────
    (
        "add notification_prefs and copy_trade_enabled to users",
        """
        ALTER TABLE users
          ADD COLUMN IF NOT EXISTS notification_prefs JSONB DEFAULT '{"signal_alerts":true,"trade_execution":true,"daily_pnl":true,"drawdown_warning":true,"news_reminder":true,"email_notifications":false,"push_notifications":false}',
          ADD COLUMN IF NOT EXISTS copy_trade_enabled BOOLEAN DEFAULT FALSE
        """,
    ),
    # ── Community channels table ─────────────────────────────────────────────
    (
        "create community_channels table",
        """
        CREATE TABLE IF NOT EXISTS community_channels (
          id          SERIAL       PRIMARY KEY,
          name        VARCHAR(80)  NOT NULL,
          chat_id     TEXT         NOT NULL UNIQUE,
          channel_type VARCHAR(20) NOT NULL DEFAULT 'community',
          description TEXT         NOT NULL DEFAULT '',
          is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
          member_count INT         NOT NULL DEFAULT 0,
          created_at  TIMESTAMPTZ  DEFAULT NOW()
        )
        """,
    ),
    (
        "seed default plans",
        """
        INSERT INTO plan_config (plan_id, name, price, color, popular, sort_order, features) VALUES
          ('community', 'Community',  0,   '#8899b4', false, 0, '{"pairs":0,"mt5_accounts":0,"dashboard":false,"signals_web":false,"signals_tg_drops":true,"tg_bot_approve":false,"tg_bot_settings":false,"auto_execute":false,"copy_trade":false,"api_access":false,"mobile_app":false,"priority_support":false}'),
          ('starter',   'Starter',   29,   '#4f8ef7', false, 1, '{"pairs":2,"mt5_accounts":1,"dashboard":true,"signals_web":true,"signals_tg_drops":true,"tg_bot_approve":false,"tg_bot_settings":false,"auto_execute":false,"copy_trade":false,"api_access":false,"mobile_app":false,"priority_support":false}'),
          ('trader',    'Trader',    79,   '#00e5cc', true,  2, '{"pairs":5,"mt5_accounts":1,"dashboard":true,"signals_web":true,"signals_tg_drops":true,"tg_bot_approve":true,"tg_bot_settings":false,"auto_execute":false,"copy_trade":true,"api_access":false,"mobile_app":true,"priority_support":false}'),
          ('pro',       'Pro',      149,   '#f0b429', false, 3, '{"pairs":5,"mt5_accounts":2,"dashboard":true,"signals_web":true,"signals_tg_drops":true,"tg_bot_approve":true,"tg_bot_settings":true,"auto_execute":true,"copy_trade":true,"api_access":false,"mobile_app":true,"priority_support":true}'),
          ('elite',     'Elite',    299,   '#8b5cf6', false, 4, '{"pairs":5,"mt5_accounts":5,"dashboard":true,"signals_web":true,"signals_tg_drops":true,"tg_bot_approve":true,"tg_bot_settings":true,"auto_execute":true,"copy_trade":true,"api_access":true,"mobile_app":true,"priority_support":true}')
        ON CONFLICT (plan_id) DO NOTHING
        """,
    ),
]


async def run_migrations() -> None:
    """Apply all pending migrations. Safe to call on every startup."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        for description, sql in MIGRATIONS:
            try:
                await conn.execute(sql.strip())
                logger.info("Migration OK: %s", description)
            except Exception as exc:
                logger.error("Migration FAILED (%s): %s", description, exc)
                raise
