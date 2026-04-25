# Trading AI SaaS V3 — Claude Code Context

## What This Project Is
A multi-tenant forex trading SaaS platform. Price action strategy (BOS + 
Supply/Demand + Order Blocks) + XGBoost AI + MetaTrader 5 execution.
Full docs in /docs/ folder — read them before writing any code.

## Current Phase
PHASE 1 — Foundation (Weeks 1–3)
See docs/Trading_AI_V3_Master_Review.docx Section 5 for the full phase plan.

## Non-Negotiable Architecture Decisions
- Database: TimescaleDB (NOT plain Postgres). Chunk intervals per schema.sql.
- Async: asyncpg for FastAPI routes. psycopg2 for Celery tasks (NEVER mix).
- AI: XGBoost only. Walk-forward validation only (never k-fold).
- Auth: Supabase JWT + PostgreSQL Row-Level Security at DB layer.
- Bridge: Primary + Hot Standby (2 Windows VPS). Never single bridge.

## Critical Rules
- Celery tasks MUST use database/sync_connection.py (get_sync_db)
- FastAPI routes MUST use database/connection.py (get_db / asyncpg)
- All 6 corrections from Master Review doc are already fixed in /fixed_files/
- Do NOT rewrite files in /fixed_files/ — use them as-is at the right phase

## File Structure
See Technical Docs Chapter 10 for the complete directory layout.

## Tech Stack
Python 3.11 · FastAPI · TimescaleDB · Redis · Celery · XGBoost · 
React 18 · Stripe · Supabase JWT · python-telegram-bot · 
React Native (mobile, later phases)

## What NOT to Do
- Do not use plain PostgreSQL instead of TimescaleDB
- Do not use k-fold cross validation on the AI model
- Do not put asyncpg calls inside Celery tasks
- Do not start Phase 2 until Phase 1 quality gates pass