-- Migration: add ohlc_m30 and ohlc_h1 hypertables
-- Safe to re-run — uses IF NOT EXISTS / DO $$ guards

-- ── M30 OHLC ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ohlc_m30 (
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

DO $$ BEGIN
    PERFORM create_hypertable(
        'ohlc_m30', 'time',
        chunk_time_interval => INTERVAL '2 months',
        if_not_exists => TRUE
    );
END $$;

CREATE INDEX IF NOT EXISTS idx_ohlc_m30_symbol_time ON ohlc_m30(symbol, time DESC);

-- ── H1 OHLC ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ohlc_h1 (
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

DO $$ BEGIN
    PERFORM create_hypertable(
        'ohlc_h1', 'time',
        chunk_time_interval => INTERVAL '3 months',
        if_not_exists => TRUE
    );
END $$;

CREATE INDEX IF NOT EXISTS idx_ohlc_h1_symbol_time ON ohlc_h1(symbol, time DESC);
