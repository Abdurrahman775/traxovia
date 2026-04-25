-- Trading AI SaaS V3 — database/materialized_views.sql
-- Run AFTER schema.sql. Requires TimescaleDB + the trades table to exist.
--
-- All three views use REFRESH MATERIALIZED VIEW CONCURRENTLY (fired every 15
-- minutes by the Celery task scheduler/tasks.py). CONCURRENTLY requires at
-- least one UNIQUE index on each view — without it Postgres falls back to a
-- blocking refresh that locks the view for the duration of the query.
--
-- Correction 3.5 (Master Review): mv_daily_pnl had no unique index, causing
-- CONCURRENTLY to silently fall back to a blocking refresh. Fixed here with
-- idx_mv_daily_pnl_u on (user_id, trade_date).

-- ─────────────────────────────────────────────────────────────────────────────
-- VIEW 1: Daily P&L per user
-- Drives the P&L calendar and daily breakdown widgets on the dashboard.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW mv_daily_pnl AS
SELECT
    user_id,
    DATE(entry_time)                                              AS trade_date,
    COUNT(*)                                                      AS trade_count,
    SUM(pnl_r)                                                    AS total_r,
    SUM(CASE WHEN pnl_r > 0 THEN 1 ELSE 0 END)                   AS wins,
    SUM(CASE WHEN pnl_r < 0 THEN 1 ELSE 0 END)                   AS losses,
    ROUND(AVG(pnl_r)::NUMERIC, 4)                                 AS avg_r
FROM trades
WHERE status = 'closed'
GROUP BY user_id, DATE(entry_time)
WITH DATA;

-- Correction 3.5: UNIQUE index required for CONCURRENT refresh.
-- Named _u to distinguish it from the lookup index below.
CREATE UNIQUE INDEX idx_mv_daily_pnl_u  ON mv_daily_pnl (user_id, trade_date);

-- Lookup index for dashboard queries filtered by date range.
CREATE INDEX        idx_mv_daily_pnl    ON mv_daily_pnl (user_id, trade_date DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- VIEW 2: Rolling 30-day performance per user
-- Drives the headline stats bar: win rate, net R, expectancy, best/worst trade.
-- One row per user — O(1) lookup instead of a full trades table scan.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW mv_rolling_performance AS
SELECT
    user_id,
    COUNT(*)                                                            AS total_trades,
    ROUND(AVG(CASE WHEN pnl_r > 0 THEN 100.0 ELSE 0 END), 1)         AS win_rate_pct,
    ROUND(SUM(pnl_r)::NUMERIC, 2)                                      AS net_r,
    ROUND(AVG(pnl_r)::NUMERIC, 3)                                      AS expectancy_r,
    MAX(pnl_r)                                                          AS best_trade_r,
    MIN(pnl_r)                                                          AS worst_trade_r,
    NOW()                                                               AS last_updated
FROM trades
WHERE status = 'closed'
  AND entry_time >= NOW() - INTERVAL '30 days'
GROUP BY user_id
WITH DATA;

-- UNIQUE index satisfies CONCURRENT refresh requirement and is also the
-- primary lookup key (one row per user).
CREATE UNIQUE INDEX idx_mv_rolling ON mv_rolling_performance (user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- VIEW 3: Performance broken down by trading pair per user
-- Drives the "By Pair" analytics tab on the dashboard.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW mv_performance_by_pair AS
SELECT
    user_id,
    pair,
    COUNT(*)                                                            AS trades,
    ROUND(AVG(CASE WHEN pnl_r > 0 THEN 100.0 ELSE 0 END), 1)         AS win_rate_pct,
    ROUND(SUM(pnl_r)::NUMERIC, 2)                                      AS net_r,
    ROUND(AVG(pnl_r)::NUMERIC, 3)                                      AS avg_r
FROM trades
WHERE status = 'closed'
GROUP BY user_id, pair
WITH DATA;

-- UNIQUE index on (user_id, pair) required for CONCURRENT refresh.
CREATE UNIQUE INDEX idx_mv_pair_u ON mv_performance_by_pair (user_id, pair);

-- Lookup index ordered for the dashboard's pair breakdown queries.
CREATE INDEX        idx_mv_pair   ON mv_performance_by_pair (user_id, pair);

-- ─────────────────────────────────────────────────────────────────────────────
-- MANUAL REFRESH (run once after initial data load, then Celery takes over)
-- ─────────────────────────────────────────────────────────────────────────────

-- REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_pnl;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mv_rolling_performance;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mv_performance_by_pair;
