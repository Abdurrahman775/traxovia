-- Trading AI SaaS V3 — database/rls_policies.sql
-- Run AFTER schema.sql.
--
-- Strategy: FastAPI sets `app.current_user_id` as a session-local variable at
-- the start of every request (see database/connection.py). Policies read that
-- value to enforce per-user isolation. The admin role holds BYPASSRLS so it is
-- never subject to these policies.
--
-- To test isolation after applying:
--   SET LOCAL app.current_user_id = '<user_a_uuid>';
--   SELECT * FROM trades;          -- must return only user A rows
--   SET LOCAL app.current_user_id = '<user_b_uuid>';
--   SELECT * FROM trades;          -- must return only user B rows

-- ─────────────────────────────────────────────────────────────────────────────
-- ROLES
-- ─────────────────────────────────────────────────────────────────────────────

-- Application role used by FastAPI / asyncpg connections.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trading_app') THEN
        CREATE ROLE trading_app LOGIN;
    END IF;
END$$;

-- Admin role — BYPASSRLS means these policies never apply to it.
-- Grant this role only to trusted operator connections (migrations, support tooling).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trading_admin') THEN
        CREATE ROLE trading_admin LOGIN BYPASSRLS;
    END IF;
END$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- HELPER: current user UUID
-- Reads the session variable set by database/connection.py at request start.
-- Returns NULL (not an error) when no user is set — all policies then return
-- FALSE so the row is invisible, which is the safe default.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION current_user_id() RETURNS UUID
    LANGUAGE sql STABLE SECURITY DEFINER AS
$$
    SELECT NULLIF(current_setting('app.current_user_id', true), '')::UUID
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: trades
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades FORCE ROW LEVEL SECURITY;   -- applies even to the table owner

DROP POLICY IF EXISTS trades_select  ON trades;
DROP POLICY IF EXISTS trades_insert  ON trades;
DROP POLICY IF EXISTS trades_update  ON trades;

CREATE POLICY trades_select ON trades
    FOR SELECT
    USING (user_id = current_user_id());

CREATE POLICY trades_insert ON trades
    FOR INSERT
    WITH CHECK (user_id = current_user_id());

CREATE POLICY trades_update ON trades
    FOR UPDATE
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());

-- No DELETE policy: trades are never hard-deleted by the application.
-- Admin role bypasses RLS for support/migration use.

GRANT SELECT, INSERT, UPDATE ON trades TO trading_app;

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: trade_signals
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE trade_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_signals FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS trade_signals_select ON trade_signals;
DROP POLICY IF EXISTS trade_signals_insert ON trade_signals;
DROP POLICY IF EXISTS trade_signals_update ON trade_signals;

CREATE POLICY trade_signals_select ON trade_signals
    FOR SELECT
    USING (user_id = current_user_id());

CREATE POLICY trade_signals_insert ON trade_signals
    FOR INSERT
    WITH CHECK (user_id = current_user_id());

CREATE POLICY trade_signals_update ON trade_signals
    FOR UPDATE
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());

GRANT SELECT, INSERT, UPDATE ON trade_signals TO trading_app;

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: risk_state
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE risk_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_state FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS risk_state_select ON risk_state;
DROP POLICY IF EXISTS risk_state_insert ON risk_state;
DROP POLICY IF EXISTS risk_state_update ON risk_state;

CREATE POLICY risk_state_select ON risk_state
    FOR SELECT
    USING (user_id = current_user_id());

CREATE POLICY risk_state_insert ON risk_state
    FOR INSERT
    WITH CHECK (user_id = current_user_id());

CREATE POLICY risk_state_update ON risk_state
    FOR UPDATE
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());

GRANT SELECT, INSERT, UPDATE ON risk_state TO trading_app;

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: feature_store
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE feature_store ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_store FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS feature_store_select ON feature_store;
DROP POLICY IF EXISTS feature_store_insert ON feature_store;
DROP POLICY IF EXISTS feature_store_update ON feature_store;

CREATE POLICY feature_store_select ON feature_store
    FOR SELECT
    USING (user_id = current_user_id());

CREATE POLICY feature_store_insert ON feature_store
    FOR INSERT
    WITH CHECK (user_id = current_user_id());

-- UPDATE is needed by feedback_loop.py to write outcome + pnl_r on trade close.
CREATE POLICY feature_store_update ON feature_store
    FOR UPDATE
    USING  (user_id = current_user_id())
    WITH CHECK (user_id = current_user_id());

GRANT SELECT, INSERT, UPDATE ON feature_store TO trading_app;

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLE: audit_log
-- Audit rows are immutable once written — no UPDATE policy is created.
-- Users can read their own log; the app writes on their behalf at service layer.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_log_select ON audit_log;
DROP POLICY IF EXISTS audit_log_insert ON audit_log;

CREATE POLICY audit_log_select ON audit_log
    FOR SELECT
    USING (user_id = current_user_id());

CREATE POLICY audit_log_insert ON audit_log
    FOR INSERT
    WITH CHECK (user_id = current_user_id());

-- No UPDATE or DELETE: audit_log rows are immutable by design.
-- Admin bypasses RLS if a row must be corrected via direct DB access.

GRANT SELECT, INSERT ON audit_log TO trading_app;

-- ─────────────────────────────────────────────────────────────────────────────
-- BRIDGE WATCHDOG EXCEPTION
-- bridge_watchdog.py writes to risk_state for ALL users when the bridge goes
-- offline (SET trading_allowed=FALSE). It does not run as a per-user request,
-- so it must connect as trading_admin (which bypasses RLS) for those bulk
-- UPDATE statements.
-- ─────────────────────────────────────────────────────────────────────────────

GRANT SELECT, INSERT, UPDATE ON risk_state    TO trading_admin;
GRANT SELECT, INSERT, UPDATE ON trades        TO trading_admin;
GRANT SELECT, INSERT, UPDATE ON trade_signals TO trading_admin;
GRANT SELECT, INSERT, UPDATE ON feature_store TO trading_admin;
GRANT SELECT, INSERT         ON audit_log     TO trading_admin;

-- ─────────────────────────────────────────────────────────────────────────────
-- VERIFICATION QUERIES (run manually to confirm isolation)
-- ─────────────────────────────────────────────────────────────────────────────

-- -- Step 1: set user A and confirm only their rows are visible
-- SET LOCAL app.current_user_id = '<user_a_uuid>';
-- SELECT COUNT(*) FROM trades;          -- must equal user A's trade count only
-- SELECT COUNT(*) FROM audit_log;       -- must equal user A's log count only
--
-- -- Step 2: switch to user B without committing
-- SET LOCAL app.current_user_id = '<user_b_uuid>';
-- SELECT COUNT(*) FROM trades;          -- must equal user B's trade count only
--
-- -- Step 3: clear the variable — all counts must return 0 (safe default)
-- SET LOCAL app.current_user_id = '';
-- SELECT COUNT(*) FROM trades;          -- must return 0
