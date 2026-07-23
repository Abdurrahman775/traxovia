# Traxovia AI - Current State Summary

## Fixed Issues ✅
1. **News API 403** - Finnhub free tier limitation, graceful degradation implemented
2. **Regime Detector** - JWT config error fixed, API working, returns 5 pairs in "ranging" state

## System Status
- **API Server**: Running on port 8000 (traxovia-api.service)
- **Database**: TimescaleDB with H4 OHLC data (5 pairs, ~1500 bars each)
- **MT5 Bridge**: Operational on port 8001
- **Frontend**: Built in /frontend/dist

## Key Components
- **Backend**: FastAPI + Celery (--pool=solo), asyncpg/psycopg2 dual pattern
- **AI**: XGBoost 2.0.3, walk-forward validation only
- **Config**: Python 3.11 required, JWT_SECRET valid, no inline comments in .env

## Last Changes
- Fixed .env JWT_EXPIRE_MINUTES parsing error
- Added error handling to regime endpoint
- Updated Finnhub error messages for free tier
- API key saved: d8mmjk9r01...kj80 (valid but free tier)

## Project Structure
```
/home/kira/trading-bot/
├── api/routes/ (15+ route modules)
├── core/ (ai_engine, strategy_engine, risk_engine, etc)
├── database/ (asyncpg + psycopg2)
├── frontend/src/ (React + TypeScript + Tailwind)
└── scheduler/tasks.py (Celery tasks)
```
