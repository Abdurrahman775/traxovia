# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

```
backtest/
  engine.py          — event-driven bar-by-bar backtester (BacktestEngine)
  tests/
    test_lookahead.py         — placeholder (empty)
    test_regime_impact.py     — placeholder (empty)
    test_weekly_confluence.py — placeholder (empty)
```

The engine is a pure, stateless module with no DB or MT5 dependency. It is consumed by three callers:

| Caller | Purpose |
|---|---|
| `core/ai_engine/walk_forward.py` | Runs engine on each test window during walk-forward validation |
| `scripts/run_backtest.py` | Standalone script: loads OHLC from DB, runs walk-forward, prints table |
| `api/routes/admin_pairs.py` | Per-pair backtest triggered from the admin dashboard |

## Data Structures

```python
@dataclass
class Signal:
    direction:   str    # "buy" | "sell"
    sl_pips:     float  # distance from entry to SL in pips
    tp_pips:     float  # distance from entry to TP in pips
    entry_price: float  # market price at signal bar

@dataclass
class TradeRecord:
    bar_in:  int    # index of entry bar
    bar_out: int    # index of exit bar
    outcome: str    # "win" | "loss"
    pnl_r:   float  # R-multiple: tp_pips/sl_pips on win, -1.0 on loss

@dataclass
class BacktestResult:
    total_trades: int
    net_r:        float
    win_rate:     float   # percentage (0–100)
    sharpe_ratio: float   # per-trade Sharpe (mean_r / std_r), not annualised
    trade_log:    list[TradeRecord]
```

## `BacktestEngine.run(df, strategy)`

```python
engine = BacktestEngine(pip_size=0.0001)
result = engine.run(df, strategy_callable)
```

**Bar loop:** iterates every row in `df`. On each bar:
1. If a trade is active, check SL/TP against bar `low`/`high`. If hit, close and record.
2. If no active trade, call `strategy(df.iloc[:i+1])` — only past + current bar visible.
3. If strategy returns a `Signal`, open a trade at `signal.entry_price`.

**One trade at a time.** A new signal is only evaluated when `active is None`. If a strategy fires every bar it will only ever have one open trade.

**SL/TP hit order:** SL is checked before TP on each bar. If both are hit in the same bar, SL takes precedence (conservative).

**P&L calculation:**
- Win: `pnl_r = tp_pips / sl_pips` (the R-multiple; a 2R setup returns 2.0)
- Loss: `pnl_r = -1.0` always (fixed 1R risk per trade)

**Sharpe ratio:** `mean_r / std_r` across all trades (sample std dev, ddof=1). Not annualised — this is a per-trade Sharpe used for model validation gates, not portfolio reporting. Returns 0.0 with fewer than 2 trades.

**`pip_size`:** default `0.0001` (standard 5-digit forex). Must be set correctly per pair:

| Pair | `pip_size` |
|---|---|
| EURUSD, GBPUSD, AUDUSD | `0.0001` |
| USDJPY | `0.01` |
| XAUUSD | `0.10` |

Wrong `pip_size` produces correct R-multiples (they are ratio-based) but incorrect SL/TP price levels — only matters if absolute price levels are used downstream.

## `scripts/run_backtest.py` — Standalone Runner

```bash
python3 scripts/run_backtest.py                         # all pairs, M15 + H4
python3 scripts/run_backtest.py --pair EURUSD           # one pair, both timeframes
python3 scripts/run_backtest.py --pair EURUSD --timeframe M15
```

Reads OHLC from TimescaleDB (`DATABASE_URL`), wraps the built-in BOS strategy, runs `WalkForwardValidator` (252-bar train / 63-bar test / 21-bar step), and prints a results table. Exits with code 1 if any pair fails.

**Built-in BOS strategy** (for reference validation, not production signals):
- 50-bar rolling window per bar
- Gate 1: `RegimeClassifier` — skip if `signal_gate == "blocked"`
- Gate 2: `BOSIdentifier(n=3)` — entry on bullish or bearish BOS on the last bar
- Fixed SL = 20 pips, TP = 40 pips (2R for all pairs)

## No-Lookahead Guarantee

The strategy callback always receives `df.iloc[:i+1]` — a slice ending at the current bar. It never sees future bars. This is the primary lookahead bias protection; `backtest/tests/test_lookahead.py` exists as a placeholder for formal lookahead tests.

## Non-Negotiable Rules

- **The strategy callable must only use data up to the current bar.** Using `df.iloc[-1]` on the full DataFrame inside a strategy is a lookahead bug — the engine passes the correct slice, but a strategy that indexes the original full `df` by reference bypasses this.
- **SL is checked before TP.** Do not swap the order — it makes the engine optimistic and invalidates walk-forward results.
- **Loss `pnl_r` is always `-1.0`.** This is intentional: the system risks exactly 1R per trade. Do not compute loss R from price distance.
- **Walk-forward only.** `WalkForwardValidator` is the only permitted evaluation harness. Never evaluate on the full dataset without time-ordered splits.
- **`pip_size` must match the pair** when computing SL/TP price levels. Pass it explicitly — never rely on the default `0.0001` for JPY or XAUUSD pairs.
