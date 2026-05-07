-- Plan configuration table — admin-editable plan definitions
-- Run: psql -U <user> -d <db> -f database/migrations/create_plan_config.sql

CREATE TABLE IF NOT EXISTS plan_config (
  plan_id    VARCHAR(20)   PRIMARY KEY,
  name       VARCHAR(50)   NOT NULL,
  price      NUMERIC(8,2)  NOT NULL DEFAULT 0,
  color      VARCHAR(20)   NOT NULL DEFAULT '#8899b4',
  popular    BOOLEAN       NOT NULL DEFAULT FALSE,
  sort_order INT           NOT NULL DEFAULT 0,
  is_active  BOOLEAN       NOT NULL DEFAULT TRUE,
  features   JSONB         NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ   DEFAULT NOW()
);

INSERT INTO plan_config (plan_id, name, price, color, popular, sort_order, features) VALUES
  ('community', 'Community', 0,   '#8899b4', false, 0, '{"pairs":0,"mt5_accounts":0,"dashboard":false,"signals_web":false,"signals_tg_drops":true,"tg_bot_approve":false,"tg_bot_settings":false,"auto_execute":false,"copy_trade":false,"api_access":false,"mobile_app":false,"priority_support":false}'),
  ('starter',   'Starter',   29,  '#4f8ef7', false, 1, '{"pairs":2,"mt5_accounts":1,"dashboard":true,"signals_web":true,"signals_tg_drops":true,"tg_bot_approve":false,"tg_bot_settings":false,"auto_execute":false,"copy_trade":false,"api_access":false,"mobile_app":false,"priority_support":false}'),
  ('trader',    'Trader',    79,  '#00e5cc', true,  2, '{"pairs":5,"mt5_accounts":1,"dashboard":true,"signals_web":true,"signals_tg_drops":true,"tg_bot_approve":true,"tg_bot_settings":false,"auto_execute":false,"copy_trade":true,"api_access":false,"mobile_app":true,"priority_support":false}'),
  ('pro',       'Pro',       149, '#f0b429', false, 3, '{"pairs":5,"mt5_accounts":2,"dashboard":true,"signals_web":true,"signals_tg_drops":true,"tg_bot_approve":true,"tg_bot_settings":true,"auto_execute":true,"copy_trade":true,"api_access":false,"mobile_app":true,"priority_support":true}'),
  ('elite',     'Elite',     299, '#8b5cf6', false, 4, '{"pairs":5,"mt5_accounts":5,"dashboard":true,"signals_web":true,"signals_tg_drops":true,"tg_bot_approve":true,"tg_bot_settings":true,"auto_execute":true,"copy_trade":true,"api_access":true,"mobile_app":true,"priority_support":true}')
ON CONFLICT (plan_id) DO NOTHING;
