-- Trading AI SaaS V3 — database/schema.sql
-- TimescaleDB required. Run with psql -U <user> -d <db> -f schema.sql
-- Apply AFTER enabling the TimescaleDB extension.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 1: CORE APPLICATION TABLES (regular PostgreSQL tables)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE users (
    id                          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email                       VARCHAR(255) NOT NULL UNIQUE,
    password_hash               VARCHAR(255) NOT NULL,
    plan                        VARCHAR(20)  NOT NULL DEFAULT 'community',
    -- plan values: community | starter | trader | pro | elite | trial
    stripe_customer_id          VARCHAR(100),
    telegram_chat_id            BIGINT,
    signup_ip                   INET,                          -- Correction 2.5: fraud guard
    trial_expires_at            TIMESTAMPTZ,
    is_paper_mode               BOOLEAN      NOT NULL DEFAULT FALSE,
    referral_code               VARCHAR(20)  UNIQUE,
    referred_by                 UUID         REFERENCES users(id),
    weekly_confluence_enabled   BOOLEAN      NOT NULL DEFAULT TRUE,
    weekly_confluence_strictness VARCHAR(10) NOT NULL DEFAULT 'strict',
    base_risk_pct               DECIMAL(5,4) NOT NULL DEFAULT 0.01,
    max_trades_per_day          INTEGER      NOT NULL DEFAULT 3,
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT users_plan_check CHECK (
        plan IN ('community', 'starter', 'trader', 'pro', 'elite', 'trial')
    ),
    CONSTRAINT users_base_risk_check CHECK (base_risk_pct BETWEEN 0.0025 AND 0.02)
);

CREATE INDEX idx_users_email        ON users(email);
CREATE INDEX idx_users_referral_code ON users(referral_code);
CREATE INDEX idx_users_plan         ON users(plan);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE mt5_accounts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_number  BIGINT      NOT NULL,
    broker          VARCHAR(100) NOT NULL DEFAULT 'Exness',
    is_demo         BOOLEAN     NOT NULL DEFAULT FALSE,
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    account_balance DECIMAL(12,2) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT mt5_accounts_unique_active UNIQUE (user_id, account_number)
);

CREATE INDEX idx_mt5_accounts_user_id ON mt5_accounts(user_id);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE model_versions (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    version          VARCHAR(50) NOT NULL UNIQUE,
    file_path        VARCHAR(255),
    oos_sharpe       DECIMAL(8,4),
    oos_win_rate     DECIMAL(6,3),
    feature_count    INTEGER     NOT NULL DEFAULT 50,
    training_samples INTEGER,
    active           BOOLEAN     NOT NULL DEFAULT FALSE,
    deployed_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Only one model can be active at a time
CREATE UNIQUE INDEX idx_model_versions_active ON model_versions(active) WHERE active = TRUE;

-- ─────────────────────────────────────────────────────────────────────────────

-- Per-user daily risk state. One row per user per trading day.
-- Improvement 3.1: model_version_id FK tracks which model issued signals for this day.
CREATE TABLE risk_state (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date                DATE        NOT NULL DEFAULT CURRENT_DATE,
    account_balance     DECIMAL(12,2) NOT NULL DEFAULT 0,
    peak_balance        DECIMAL(12,2) NOT NULL DEFAULT 0,
    total_drawdown_pct  DECIMAL(6,3)  NOT NULL DEFAULT 0,
    drawdown_stage      INTEGER       NOT NULL DEFAULT 0,
    -- stage values: 0=normal | 1=caution (10%) | 2=restricted (12%) | 3=paused (15%)
    trading_allowed     BOOLEAN       NOT NULL DEFAULT TRUE,
    block_reason        VARCHAR(255),
    daily_trades        INTEGER       NOT NULL DEFAULT 0,
    daily_pnl_r         DECIMAL(8,4)  NOT NULL DEFAULT 0,
    model_version_id    UUID          REFERENCES model_versions(id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT risk_state_unique_user_date UNIQUE (user_id, date),
    CONSTRAINT risk_state_stage_check CHECK (drawdown_stage BETWEEN 0 AND 3)
);

CREATE INDEX idx_risk_state_user_date ON risk_state(user_id, date DESC);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE trade_signals (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pair            VARCHAR(10) NOT NULL,
    direction       VARCHAR(10) NOT NULL,
    timeframe       VARCHAR(10) NOT NULL DEFAULT 'M15',
    entry_price     DECIMAL(12,5),
    stop_loss       DECIMAL(12,5),
    take_profit     DECIMAL(12,5),
    lot_size        DECIMAL(10,4),
    regime          VARCHAR(20),
    -- regime values: trending | ranging | volatile
    regime_adx      DECIMAL(8,4),
    ai_probability  DECIMAL(5,4),
    ai_features     JSONB,
    shap_values     JSONB,
    reasoning       TEXT,
    gate_results    JSONB,
    -- gate_results stores per-gate pass/fail log for every signal
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- status values: pending | approved | rejected | auto_executed | expired
    triggered_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT trade_signals_direction_check CHECK (direction IN ('buy', 'sell')),
    CONSTRAINT trade_signals_status_check CHECK (
        status IN ('pending', 'approved', 'rejected', 'auto_executed', 'expired')
    )
);

CREATE INDEX idx_trade_signals_user_id     ON trade_signals(user_id, triggered_at DESC);
CREATE INDEX idx_trade_signals_status      ON trade_signals(status) WHERE status = 'pending';
CREATE INDEX idx_trade_signals_pair        ON trade_signals(pair, triggered_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE trades (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    signal_id       UUID        REFERENCES trade_signals(id),
    pair            VARCHAR(10) NOT NULL,
    direction       VARCHAR(10) NOT NULL,
    entry_price     DECIMAL(12,5),
    exit_price      DECIMAL(12,5),
    stop_loss       DECIMAL(12,5),
    take_profit     DECIMAL(12,5),
    lot_size        DECIMAL(10,4),
    pnl_r           DECIMAL(8,4),
    pips            DECIMAL(8,1),
    commission      DECIMAL(8,2),
    status          VARCHAR(20)  NOT NULL DEFAULT 'open',
    -- status values: open | closed | cancelled
    entry_time      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    exit_time       TIMESTAMPTZ,
    duration_hours  DECIMAL(8,2),
    mt5_ticket      BIGINT,
    is_paper        BOOLEAN      NOT NULL DEFAULT FALSE,
    partial_closed  BOOLEAN      NOT NULL DEFAULT FALSE,
    regime          VARCHAR(20),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT trades_direction_check CHECK (direction IN ('buy', 'sell')),
    CONSTRAINT trades_status_check CHECK (status IN ('open', 'closed', 'cancelled'))
);

-- Correction 3.7: compound index for materialized view refresh performance.
-- The 3 mat views all GROUP BY user_id and filter by entry_time — without this
-- each 15-minute refresh does a full table scan.
CREATE INDEX idx_trades_user_time ON trades(user_id, entry_time DESC) WHERE status = 'closed';

CREATE INDEX idx_trades_user_status  ON trades(user_id, status);
CREATE INDEX idx_trades_pair         ON trades(pair, entry_time DESC);
CREATE INDEX idx_trades_mt5_ticket   ON trades(mt5_ticket) WHERE mt5_ticket IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────

-- Immutable event log — one row per account action.
-- 8 action categories per PRD Section 11.4:
--   authentication | signal_action | risk_change | mt5_binding |
--   billing | ai_model | bridge_event | admin_action
CREATE TABLE audit_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action      VARCHAR(100) NOT NULL,
    detail      TEXT,
    ip_address  INET,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user_id    ON audit_log(user_id, created_at DESC);
CREATE INDEX idx_audit_log_action     ON audit_log(action, created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────

-- Singleton table: one row tracks live bridge state.
-- Written by bridge_watchdog.py; read by risk_manager and dashboard.
CREATE TABLE bridge_state (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    active_url      VARCHAR(255) NOT NULL,
    primary_url     VARCHAR(255) NOT NULL,
    standby_url     VARCHAR(255) NOT NULL,
    last_heartbeat  TIMESTAMPTZ,
    offline_since   TIMESTAMPTZ,
    trading_paused  BOOLEAN      NOT NULL DEFAULT FALSE,
    failover_count  INTEGER      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE community_members (
    id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_chat_id    BIGINT  NOT NULL UNIQUE,
    signals_received    INTEGER NOT NULL DEFAULT 0,
    joined_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 2: TIMESCALEDB HYPERTABLES
-- Chapter 6 chunk intervals: M15=1 month, H4=6 months, W1=2 years
-- ─────────────────────────────────────────────────────────────────────────────

-- M15 OHLC — 96 rows/day per symbol. 1-month chunks = 3–5× faster range queries.
CREATE TABLE ohlc_m15 (
    time    TIMESTAMPTZ  NOT NULL,
    symbol  VARCHAR(10)  NOT NULL,
    open    DECIMAL(12,5),
    high    DECIMAL(12,5),
    low     DECIMAL(12,5),
    close   DECIMAL(12,5),
    volume  BIGINT,
    spread  DECIMAL(8,5),
    PRIMARY KEY (time, symbol)
);

SELECT create_hypertable(
    'ohlc_m15', 'time',
    chunk_time_interval => INTERVAL '1 month'
);

CREATE INDEX idx_ohlc_m15_symbol_time ON ohlc_m15(symbol, time DESC);

-- ─────────────────────────────────────────────────────────────────────────────

-- H4 OHLC — 6 rows/day per symbol. 6-month chunks = 8–12× faster range queries.
CREATE TABLE ohlc_h4 (
    time    TIMESTAMPTZ  NOT NULL,
    symbol  VARCHAR(10)  NOT NULL,
    open    DECIMAL(12,5),
    high    DECIMAL(12,5),
    low     DECIMAL(12,5),
    close   DECIMAL(12,5),
    volume  BIGINT,
    spread  DECIMAL(8,5),
    PRIMARY KEY (time, symbol)
);

SELECT create_hypertable(
    'ohlc_h4', 'time',
    chunk_time_interval => INTERVAL '6 months'
);

CREATE INDEX idx_ohlc_h4_symbol_time ON ohlc_h4(symbol, time DESC);

-- ─────────────────────────────────────────────────────────────────────────────

-- W1 OHLC — 1 row/week per symbol. 2-year chunks optimal for weekly data.
-- No spread column: weekly candles don't have a meaningful per-bar spread.
CREATE TABLE ohlc_w1 (
    time    TIMESTAMPTZ  NOT NULL,
    symbol  VARCHAR(10)  NOT NULL,
    open    DECIMAL(12,5),
    high    DECIMAL(12,5),
    low     DECIMAL(12,5),
    close   DECIMAL(12,5),
    volume  BIGINT,
    PRIMARY KEY (time, symbol)
);

SELECT create_hypertable(
    'ohlc_w1', 'time',
    chunk_time_interval => INTERVAL '2 years'
);

CREATE INDEX idx_ohlc_w1_symbol_time ON ohlc_w1(symbol, time DESC);

-- ─────────────────────────────────────────────────────────────────────────────

-- feature_store: one row per signal at M15 frequency.
-- Features written at signal time (outcome=NULL), updated when trade closes.
-- Hypertable with 1-month chunks (same density as M15 OHLC).
CREATE TABLE feature_store (
    time        TIMESTAMPTZ  NOT NULL,
    symbol      VARCHAR(10)  NOT NULL,
    timeframe   VARCHAR(10)  NOT NULL DEFAULT 'M15',
    user_id     UUID         REFERENCES users(id) ON DELETE SET NULL,
    signal_id   UUID         REFERENCES trade_signals(id) ON DELETE SET NULL,
    features    JSONB        NOT NULL,  -- all 50 XGBoost features
    outcome     VARCHAR(20),            -- NULL → 'win' | 'loss' | 'breakeven' on close
    pnl_r       DECIMAL(8,4),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (time, symbol, timeframe)
);

SELECT create_hypertable(
    'feature_store', 'time',
    chunk_time_interval => INTERVAL '1 month'
);

CREATE INDEX idx_feature_store_outcome ON feature_store(outcome, time DESC)
    WHERE outcome IS NOT NULL;
CREATE INDEX idx_feature_store_symbol  ON feature_store(symbol, time DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 3: VERIFICATION QUERY
-- Run after applying schema to confirm all hypertables and chunk intervals.
-- ─────────────────────────────────────────────────────────────────────────────

-- SELECT hypertable_name, num_chunks, chunk_time_interval
-- FROM timescaledb_information.hypertables
-- ORDER BY hypertable_name;
--
-- Expected:
--   feature_store  | <n> | 1 mon
--   ohlc_h4        | <n> | 6 mons
--   ohlc_m15       | <n> | 1 mon
--   ohlc_w1        | <n> | 2 years
