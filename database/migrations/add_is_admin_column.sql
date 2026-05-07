-- Add is_admin column to users table.
-- Existing elite users are granted admin status to preserve current behaviour.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE users SET is_admin = TRUE WHERE plan = 'elite';
