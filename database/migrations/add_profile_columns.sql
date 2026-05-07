-- Add display_name and avatar_url to users table
-- Run: psql -U <user> -d <db> -f database/migrations/add_profile_columns.sql

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS display_name VARCHAR(80),
  ADD COLUMN IF NOT EXISTS avatar_url   TEXT;
