-- Add managed_pairs table
CREATE TABLE IF NOT EXISTS managed_pairs (
    symbol          VARCHAR(12) PRIMARY KEY,
    display_name    VARCHAR(100) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    session_windows JSONB,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by        UUID REFERENCES users(id),
    last_tested_at  TIMESTAMPTZ,
    test_result     JSONB,
    notes           TEXT
);

COMMENT ON TABLE managed_pairs IS 'Trading pairs configured for the strategy';
