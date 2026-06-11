# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

All trading logic lives here. The five engines are strictly layered — `strategy_engine` is the top-level orchestrator; everything else feeds into it.

```
core/
  strategy_engine/   ← top-level signal pipeline (signal_generator.py is the entry point)
  structure_engine/  ← market structure primitives (BOS, OB, swings, regime)
  risk_engine/       ← position sizing, drawdown protocol, spread/correlation filters
  ai_engine/         ← XGBoost model: features, training, prediction, SHAP, feedback
  execution_engine/  ← MT5 order placement and trade lifecycle management
```

## Signal Pipeline (`strategy_engine/signal_generator.py`)

`generate_signal()` is the single entry point for the entire system. It runs 8 sequential gates; any gate failure returns immediately with `{"signal": None, "gate": N, "reason": "..."}`. A passing signal returns `{"signal": "generated", "gate": 7, ...}` plus all entry parameters.

| Gate | Check | Blocks on |
|---|---|---|
| 0a | Daily circuit breaker | `daily_pnl_r ≤ -3.0R` |
| 0b | Max concurrent trades | `open_trades ≥ 2` |
| 0c | Correlated pair filter | correlated pair already open |
| 0d | Session / killzone | outside valid trading hours |
| 0e | News filter | within event window |
| 1 | D1 market structure (`HTFStructure`) | D1 BOS blocked or unclear |
| 2 | H4 BOS bias (`BiasAnalyzer`) | no H4 bias, or H4 contradicts D1 |
| 3 | Order Block (`OrderBlockDetector`) | no unmitigated OB present |
| 3b | Fair Value Gap (`check_fvg`) | no FVG inside/near OB |
| 4b | CHoCH on M5/M15 (`detect_choch`) | no Change of Character |
| 5 | Spread check (`check_spread`) | spread > 1.5× baseline |
| 6 | Lot size sanity | `lot ≤ 0` |
| 7 | Drawdown protocol (`evaluate_drawdown`) | Stage 3 (DD ≥ 15%) |

Module-level singletons `_htf_struct`, `_bias_anl`, `_ob_det` are instantiated once. Tests patch them by dotted path (e.g., `core.strategy_engine.signal_generator._htf_struct`).

## Structure Engine

### ICT Migration (important history)

Two classes maintain **identical return interfaces** to their predecessors — do not change the return shape:

| New class | Replaced | Same interface as |
|---|---|---|
| `HTFStructure` (htf_structure.py) | `RegimeClassifier` | Returns `{"signal_gate", "regime", "adx", "d1_bias", ...}` |
| `OrderBlockDetector` (order_block_detector.py) | `ZoneDetector` | Returns `{"passed", "zone", "reason"}` where `zone` is a `Zone` dataclass |

`HTFStructure` resamples H4 candles → D1, detects swing highs/lows with `n=3` bars each side, then identifies the most recent BOS direction. This replaced the ADX regime gate because D1 BOS directly identifies institutional positioning.

`OrderBlockDetector` finds the last bearish/bullish candle before a strong impulse move (≥ 3× the OB body, confirmed over 6 bars). Only **unmitigated** OBs (price hasn't returned yet) qualify; stale OBs older than 80 M15 bars are rejected.

### Other structure primitives

- `BOSIdentifier` — adds `bullish_bos` / `bearish_bos` boolean columns to a DataFrame; swing confirmed after `n=3` bars
- `SwingDetector` — swing high/low detection feeding bias and BOS analysis
- `RegimeClassifier` — ADX + ATR-ratio regime (trending/ranging/volatile); ADX threshold 20, ATR ratio threshold 2.0; volatile check runs first
- `ZoneDetector` — legacy supply/demand zone detection; kept because `Zone` dataclass is used by `OrderBlockDetector`

## Risk Engine

### Drawdown Protocol (`drawdown_monitor.py`)

Three-stage escalation based on `total_drawdown_pct` from `risk_state` table:

| Stage | Threshold | Risk cap | Trading |
|---|---|---|---|
| 0 | < 10% | 2% (position sizer default) | ✅ allowed |
| 1 | ≥ 10% | 0.5% | ✅ allowed |
| 2 | ≥ 12% | 0.25% | ✅ allowed |
| 3 | ≥ 15% | 0% | 🛑 paused |

`evaluate_drawdown(user_id, db)` is async (uses asyncpg). It is called both at Gate 7 of the signal pipeline and after every trade close in `feedback_loop.on_trade_closed()`. Stage changes trigger a Telegram notification.

### Position Sizer (`position_sizer.py`)

`calculate_lot_size()` applies two adjustments on top of the raw `risk_pct`:
1. Halves the risk for `regime == "volatile"`
2. Caps effective risk at the DD stage cap (from `_STAGE_RISK_CAP`)

Pip value per lot: JPY pairs → 1000, XAUUSD → 100, everything else → 10.

### Spread Filter (`spread_filter.py`)

Reads live spread directly from MT5 (`symbol_info_tick`). Blocks if `current_spread > 1.5 × SPREAD_BASELINES[symbol]`. Returns `{"allowed": True}` silently on Linux (MT5 unavailable) to avoid blocking non-Windows environments.

## AI Engine

### Feature Vector

`FEATURE_NAMES` in `feature_engineer.py` defines exactly **50 features** in a fixed order — the list is `assert`-guarded. Never add, remove, or reorder entries without retraining the model and updating `model_versions`.

| Group | Count | Examples |
|---|---|---|
| Regime | 5 | `adx`, `atr_ratio`, `regime_trending` |
| Bias | 5 | `bias_bullish`, `bias_strength`, `bos_strength` |
| Zone | 6 | `in_demand_zone`, `zone_strength`, `zone_test_count` |
| Entry | 6 | `sl_pips`, `tp_pips`, `rr_ratio` |
| Weekly | 4 | `weekly_bos_strength`, `weekly_bullish` |
| Spread | 3 | `current_spread`, `spread_ratio` |
| HTF price action | 8 | `htf_body_ratio`, `htf_momentum` |
| LTF price action | 8 | `ltf_body_ratio`, `ltf_volatility` |
| Time | 5 | `hour_sin`, `hour_cos`, `session_london` |

### Model Lifecycle

- **Training** — `WalkForwardTrainer.run()` reads from `feature_store`, requires ≥ 50 samples, trains on 80% (time-ordered), evaluates OOS win rate, pickles to `models/xgboost_<version>.pkl`, records in `model_versions` table. Uses psycopg2 (sync) — called from Celery.
- **Registry** — `ModelManager` maintains an in-memory `_cache` keyed by `model_versions.id`. `get_active_model()` returns the module-level singleton. Uses psycopg2 (sync).
- **Prediction** — `ModelPredictor.predict()` returns `{signal_probability, confidence_tier, top_features, model_version}`. Tiers: `high ≥ 0.70`, `medium ≥ 0.55`, `low < 0.55`.
- **Feedback** — `feedback_loop.on_trade_closed()` labels the `feature_store` row as win/loss/breakeven (threshold ±0.1R), fires Telegram notification, re-evaluates drawdown, and optionally triggers community drop + Celery retrain check. Uses asyncpg (async) — called from FastAPI context.
- **SHAP** — `shap_analyzer.calculate_shap_async` is a Celery task; uses psycopg2 for DB reads and `asyncio.run()` for the WebSocket push.

### Walk-Forward Validation

`WalkForwardValidator` in `walk_forward.py`: 252-bar train, 63-bar test, 21-bar step, minimum 3 windows. This is the only permitted validation strategy — never k-fold.

## Execution Engine

### MT5 Executor (`mt5_executor.py`)

Wraps the `MetaTrader5` Python package. On Linux, `_MT5_AVAILABLE = False` and every public function raises `BridgeError` — imports still succeed cleanly. All code that calls MT5 must check `_MT5_AVAILABLE` first or catch `BridgeError`.

`_get_fill_mode()` reads the broker's `filling_mode` bitmask and returns the best supported mode (FOK → IOC → RETURN). This must be called per-symbol — different brokers support different modes.

`open_order()` and `close_order()` are async but internally call synchronous MT5 functions (MT5 Python API is single-threaded). Do not call these concurrently.

### Trade Manager (`trade_manager.py`)

Monitors open trades for SL/TP hits. Uses psycopg2 (sync) for DB access — designed to run in the Celery worker, not FastAPI. P&L is computed in R-multiples: `pnl_r = move / risk_per_unit` where `risk_per_unit = |entry - sl|`.

### Copy Trade (`copy_trade.py`)

Mirrors signals from a master account to follower accounts.

## Non-Negotiable Rules

- **`FEATURE_NAMES` must stay at exactly 50 entries.** The `assert len(FEATURE_NAMES) == 50` guard will catch it at import time, but a mismatch against a saved model silently corrupts predictions.
- **Walk-forward only.** Never use k-fold or random train/test splits on time-series data.
- **`HTFStructure.classify()` and `OrderBlockDetector.check_gate()` must maintain their return interfaces.** Other engines depend on these exact keys.
- **MT5 calls always go through `_require_mt5()` or check `_MT5_AVAILABLE`.** Never call `mt5.*` functions directly without the guard.
- **DB access follows the async boundary:** `evaluate_drawdown` and `feedback_loop` use asyncpg (FastAPI context); `ModelManager`, `WalkForwardTrainer`, `trade_manager`, and `shap_analyzer` use psycopg2 (Celery context).
- **Do not change the drawdown stage thresholds** (10/12/15%) or lot size caps without updating the risk documentation and Telegram notification messages.
- **Gate 0 circuit breakers are hard limits:** daily loss ≤ −3R and max 2 concurrent open trades are not configurable per-user at the code level.
