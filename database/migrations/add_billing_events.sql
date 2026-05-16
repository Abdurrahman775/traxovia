-- Migration: add billing_events idempotency table
-- Purpose: record processed Stripe webhook event IDs so retried events
--          are detected and skipped without double-processing plan changes.

CREATE TABLE IF NOT EXISTS billing_events (
    event_id     TEXT        PRIMARY KEY,
    event_type   TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE billing_events IS
  'Stripe webhook idempotency log — each event_id is inserted exactly once.';
