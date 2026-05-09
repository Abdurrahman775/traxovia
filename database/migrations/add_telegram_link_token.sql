-- Add Telegram account-linking token columns to users.
-- The token is generated on-demand via the Settings page, expires in 15 minutes,
-- and is cleared once the bot successfully links the account.
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS telegram_link_token      VARCHAR(10),
  ADD COLUMN IF NOT EXISTS telegram_link_expires_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS telegram_username        VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_users_telegram_link_token
  ON users(telegram_link_token)
  WHERE telegram_link_token IS NOT NULL;
