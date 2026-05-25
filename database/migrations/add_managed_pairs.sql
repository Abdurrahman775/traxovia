-- Migration: add_managed_pairs
-- Stores dynamically-managed trading pairs and their backtest results

CREATE TABLE IF NOT EXISTS managed_pairs (
    symbol          VARCHAR(12) PRIMARY KEY,
    display_name    VARCHAR(50) NOT NULL DEFAULT '',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    session_windows JSONB,          -- [[start_h, end_h], ...] UTC
    added_by        UUID REFERENCES users(id) ON DELETE SET NULL,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_tested_at  TIMESTAMPTZ,
    test_result     JSONB,          -- {trades, win_rate, net_r, avg_r, max_dd_r, status}
    notes           TEXT
);

-- Seed with the 5 current strategy pairs
INSERT INTO managed_pairs (symbol, display_name, is_active, session_windows) VALUES
  ('EURUSD', 'Euro / US Dollar',          TRUE, '[[4,5],[7,11],[12,14],[16,17]]'),
  ('GBPUSD', 'British Pound / US Dollar', TRUE, '[[0,1],[4,6],[9,10],[13,15]]'),
  ('USDJPY', 'US Dollar / Japanese Yen',  TRUE, '[[0,1],[3,4],[5,7],[8,9]]'),
  ('AUDUSD', 'Australian Dollar / USD',   TRUE, '[[1,2],[8,10],[12,15],[16,18]]'),
  ('XAUUSD', 'Gold / US Dollar',          TRUE, '[[7,17]]')
ON CONFLICT (symbol) DO NOTHING;
