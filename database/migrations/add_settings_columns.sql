-- Add extended settings columns to users table
-- Run: psql -U <user> -d <db> -f database/migrations/add_settings_columns.sql

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS trading_mode           VARCHAR(20)   DEFAULT 'signal_approval',
  ADD COLUMN IF NOT EXISTS news_blocking          BOOLEAN       DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS friday_cutoff          BOOLEAN       DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS risk_max_pct           NUMERIC(5,2)  DEFAULT 2.0,
  ADD COLUMN IF NOT EXISTS risk_max_drawdown_pct  NUMERIC(5,2)  DEFAULT 15.0,
  ADD COLUMN IF NOT EXISTS risk_daily_pct         NUMERIC(5,2)  DEFAULT 5.0,
  ADD COLUMN IF NOT EXISTS active_pairs           JSONB         DEFAULT '{"EUR/USD":true,"GBP/USD":true,"USD/JPY":false,"AUD/USD":false,"XAU/USD":false}',
  ADD COLUMN IF NOT EXISTS mt5_accounts           JSONB         DEFAULT '[]';
