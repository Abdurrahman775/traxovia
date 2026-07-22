# Traxovia AI — Trading Bot & Signal Platform

A full-stack algorithmic trading platform with AI-powered signal generation, real-time market data, backtesting, subscription billing, and community features. Built with FastAPI and a React frontend.

## Features

- **AI Trading Signals** — Machine learning models generate buy/sell signals from market data
- **Real-time Analytics** — Live portfolio tracking, trade history, and performance metrics
- **Backtesting Engine** — Test strategies against historical data before going live
- **Multi-tier Subscriptions** — Stripe-powered billing (Starter, Trader, Pro, Elite plans)
- **Automated Trading** — Configurable live trading loop with risk management
- **Community Features** — Telegram integration, referral system, shared signal rooms
- **Admin Panel** — User management, pair configuration, audit logs
- **Mobile Support** — Companion mobile application

## Tech Stack

- **Backend:** Python, FastAPI, Celery, Redis, PostgreSQL
- **Frontend:** React (Vite), Tailwind CSS
- **Infrastructure:** Docker, Docker Compose
- **External APIs:** Finnhub (market data), Stripe (billing), Telegram (notifications)
- **Auth:** JWT-based authentication

## Quick Start

```bash
# Copy environment file
cp .env.example .env
# Fill in your API keys (JWT_SECRET, Stripe, Finnhub, Telegram)

# Start with Docker
docker-compose up -d

# Or run manually:
# Backend
python main.py

# Frontend
cd frontend && npm install && npm run dev
```

## Project Structure

```
traxovia/
├── api/              # FastAPI route handlers (auth, billing, signals, trades, admin, etc.)
├── core/             # Core business logic and configurations
├── models/           # ML models for signal generation
├── data/             # Data processing pipeline
├── backtest/         # Backtesting engine
├── database/         # Database connection, migrations
├── frontend/         # React SPA (Vite)
├── mobile/           # Mobile app code
├── docs/             # Documentation
└── infra/            # Infrastructure configs
```
