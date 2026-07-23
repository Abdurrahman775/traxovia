# AGENTS.md
# Traxovia AI — Agentic Coding Guidelines

## Build / Lint / Test Commands

### Backend (FastAPI)
```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --reload    # dev
bash scripts/start_api.sh                                  # prod (port 8000)
```

### Celery
```bash
celery -A scheduler.tasks worker --pool=solo --loglevel=info    # worker
celery -A scheduler.tasks beat --loglevel=info                   # beat scheduler
```

### Testing
```bash
pytest                                     # all tests
pytest tests/test_phase1.py -v             # single file
pytest tests/test_phase1.py::test_name -v  # single test
```

### Frontend
```bash
cd frontend && npm run dev     # dev server
cd frontend && npm run build   # production → frontend/dist/
```

### Database
```bash
python database/init_db.py              # manual init
psql -h localhost -U trading_app -d trading_ai -f database/schema.sql   # apply schema
```

### MT5 Bridge
```bash
bash scripts/setup_wine_mt5.sh          # Wine + MT5 setup (10-15 min)
curl http://127.0.0.1:8001/health       # verify bridge
```

### Systemd Services
```bash
sudo systemctl start|stop|restart|status traxovia-api
sudo systemctl start|stop|restart|status traxovia-worker
sudo systemctl start|stop|restart|status traxovia-beat
sudo systemctl start|stop|restart|status tg_bot
sudo systemctl start|stop|restart|status mt5-terminal
sudo systemctl start|stop|restart|status mt5-bridge
```

### Other
```bash
python scripts/seed_admin.py          # seed admin user
python backtest/engine.py             # run backtest
python3 live_trading_loop.py          # live trading daemon
celery -A scheduler.tasks call scheduler.tasks.retrain_model   # trigger XGBoost retrain
```

## Critical Requirements

- **Python 3.11** — XGBoost 2.0.3 is built against 3.11. 3.12+ causes import errors.
- **Docker Compose V2** — use `docker compose` (not `docker-compose`). Min 24.x.
- **TimescaleDB** — hypertable chunk intervals defined in `database/schema.sql`. Not plain Postgres.
- **Celery `--pool=solo`** — MT5 Python API is single-threaded; never use other pools.
- **Supabase JWT** — `JWT_SECRET` must match Supabase project JWT secret, not a random key.
- **Telegram token** — stored in `bot_config` DB table, not `.env`. tg_bot.service must NOT use `EnvironmentFile` (`.env` has inline comments that break systemd).
- **Billing** — `stripe.Subscription.modify()` on existing sub for plan changes; never create new checkout session (double billing).

## Code Style Guidelines

### Imports
- Standard library → third-party → local, alphabetically within each group.
- Explicit imports only: `from fastapi import Depends` not `from fastapi import *`.

### Formatting
- 4-space indentation, no tabs.
- 80-character line limit.
- Max 2 blank lines between sections, max 4 nesting levels.

### Types & Data
- Type hints everywhere (parameters + return).
- `Optional[Type]` for nullable values.
- Pydantic models for all API request/response schemas.
- Type aliases for domain concepts (`PositionSize = float`).
- `asyncio_mode = auto` in pytest — all async tests auto-detected.

### Naming
| Element | Convention | Example |
|---------|-----------|---------|
| files/dirs | `snake_case` | `api/routes/trading.py` |
| variables | `snake_case` | `order_book_data` |
| functions | `snake_case` | `calculate_position_size()` |
| classes | `PascalCase` | `OrderBookManager` |
| enums | `PascalCase` | `OrderStatus` |

### Error Handling
- Specific exception types only (never bare `except:`).
- Log with context (timestamp, request ID).
- Retry for transient failures; circuit-breaker for persistent.
- No silent swallowing. No `pass` in except blocks.
- Drawdown circuit-breaker: -3R over 15 trades → pause 10 trades.

### Databases (Dual Connection Pattern)
- **FastAPI routes**: asyncpg (`get_db` from `database/connection.py`) — never psycopg2.
- **Celery tasks**: psycopg2 (`get_sync_db` from `database/sync_connection.py`) — never asyncpg.
- **Never mix**. This is enforced at the architecture level.

### AI / Strategy
- XGBoost only — never other model types.
- Walk-forward validation only — never k-fold.
- SHAP analysis for prediction explainability.
- Feature drift check runs daily at 06:00 UTC.
- Model retrain runs Sunday 02:00 UTC.

### Docstring Convention
- Public functions only.
- Include edge cases and param types.
- No internal/exploratory comments.

## DOCX / Reporting

- Always use `python-docx` (installed) for reading/writing .docx files.
- Validate created .docx with `python scripts/office/validate.py` (from docx skill).
- Arial font, US Letter page size (12240×15840 DXA), 1" margins.
- Tables need dual widths (table + each cell), DXA units only.
- Never use unicode bullets — use `LevelFormat.BULLET` numbering config.

## Copilot / Agent Rules

1. Generated code must type-hint every function parameter and return.
2. New API routes must include Pydantic request/response models.
3. Trading logic changes must preserve risk management (circuit-breaker, max trades/day, base risk %).
4. MT5 integration code must remain `--pool=solo` compatible.
5. Tests must use pytest verbose format and `asyncio_mode = auto`.
6. Frontend: Tailwind CSS utilities over custom CSS classes.
7. DB schema changes must maintain TimescaleDB hypertable structure.
8. Billing changes: always `stripe.Subscription.modify()`, never new checkout for upgrades.
9. DOCX generation: validate with `validate.py`, use `ShadingType.CLEAR`, never percentage widths.
10. Systemd unit edits: copy from `infra/` to `/etc/systemd/system/`, then `daemon-reload`.
