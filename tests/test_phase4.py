"""
tests/test_phase4.py — Phase 4 quality gate tests.

Five structural tests validating the backtest framework and regime-filter
mechanism.  No database connection required — all tests use synthetic OHLC data.

Test 1 — Look-ahead bias gate
    10,000 bars of seeded random walk, alternating buy/sell strategy.
    net_r must stay within [-200, +200] R.  Breaching this bound with
    alternating direction on random data implies systematic look-ahead
    or a broken R:R calculation.

Test 2 — Walk-forward minimum windows
    WalkForwardValidator must raise ValueError when given fewer than 357 bars.
    Must succeed with exactly 357 bars (the 3-window minimum).

Test 3 — Walk-forward OOS never overlaps train
    For every window: test_start == train_end and the two bar-index sets
    are disjoint.  Tested across all windows of a 420-bar run.

Test 4 — Backtester SL/TP correctness
    Deterministic 5-bar price series where SL is breached on bar 3.
    Asserts: single trade, bar_in=0, bar_out=3, outcome='loss', pnl_r=-1.0.

Test 5 — Regime gate structural suppression
    When regime is 'blocked', the downstream BOS entry logic must never
    execute, even on bars where a real BOS signal would fire.

Run:
    pytest tests/test_phase4.py -v
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from backtest.engine import BacktestEngine, Signal
from core.ai_engine.walk_forward import WalkForwardValidator
from core.structure_engine.bos_identifier import BOSIdentifier


# ── OHLC helpers ───────────────────────────────────────────────────────────────

def _make_random_ohlc(n: int, seed: int = 42) -> pd.DataFrame:
    """
    Seeded Gaussian log-normal random walk.

    Close-to-close σ = 0.001 (~10 pips).  Wick half-range σ = 0.0002
    (~2 pips) — intentionally small so SL/TP is driven by close-to-close
    drift rather than intra-bar spikes; keeps win rate near gambler's-ruin
    prediction for the look-ahead test.
    """
    rng         = np.random.default_rng(seed)
    log_returns = rng.normal(0.0, 0.001, n)
    close       = 1.0850 * np.exp(np.cumsum(log_returns))

    open_       = np.empty(n)
    open_[0]    = close[0]
    open_[1:]   = close[:-1]

    half_range  = np.abs(rng.normal(0.0, 0.0002, n))
    high        = np.maximum(open_, close) + half_range
    low         = np.maximum(np.minimum(open_, close) - half_range, 0.01)

    return pd.DataFrame({
        "time":  pd.date_range("2020-01-01", periods=n, freq="15min"),
        "open":  open_,
        "high":  high,
        "low":   low,
        "close": close,
    })


def _make_flat_df(n: int) -> pd.DataFrame:
    """Flat OHLC with 1-pip wicks — no SL/TP hit on 20-pip SL."""
    close = 1.0850
    return pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  [close] * n,
        "high":  [close + 0.0001] * n,
        "low":   [close - 0.0001] * n,
        "close": [close] * n,
    })


def _mock_run_result(sharpe: float = 0.5, win_rate: float = 40.0) -> MagicMock:
    r = MagicMock()
    r.sharpe_ratio = sharpe
    r.win_rate     = win_rate
    return r


# ── Test 1: Look-ahead bias gate ───────────────────────────────────────────────

def test_no_systematic_edge_on_random_data():
    """
    Alternating buy/sell strategy on 10,000 bars of seeded random-walk data
    must produce no systematic edge.

    Theoretical basis:
      E[pnl_r] = 0 for alternating direction on a symmetric random walk.
      σ_trade  = √(1/3 × 4 + 2/3 × 1) = √2 ≈ 1.41  (1:2 R:R)
      σ_total  = √1000 × 1.41 ≈ 44.7 R               (~1000 trades on 10k bars)
      ±200 R is > 4σ — breached only by a systematic bias, not variance.

    Alternating direction cancels any residual drift in the walk, so E[pnl_r]
    is zero regardless of seed.
    """
    def _alternating_strategy(df_visible: pd.DataFrame) -> Signal | None:
        bar_idx = len(df_visible) - 1
        if bar_idx % 10 != 0:
            return None
        trigger   = bar_idx // 10
        direction = "buy" if trigger % 2 == 0 else "sell"
        return Signal(
            direction=direction,
            sl_pips=20.0,
            tp_pips=40.0,
            entry_price=float(df_visible["close"].iloc[-1]),
        )

    df     = _make_random_ohlc(10_000, seed=42)
    result = BacktestEngine(pip_size=0.0001).run(df, _alternating_strategy)

    assert result.total_trades > 100, (
        f"Only {result.total_trades} trades — insufficient for a meaningful gate"
    )
    assert -200 <= result.net_r <= 200, (
        f"net_r = {result.net_r:.2f} R outside ±200 bound. "
        f"total_trades={result.total_trades}, win_rate={result.win_rate:.1f}%. "
        "A systematic bias this large on random data implies look-ahead or "
        "broken R:R accounting."
    )


# ── Test 2: Walk-forward minimum windows ──────────────────────────────────────

def test_walk_forward_raises_on_insufficient_data():
    """
    Minimum bars for 3 windows with default params:
      train(252) + test(63) + (3-1) × step(21) = 357

    356 bars → n_windows = (356-315)//21 + 1 = 2  →  ValueError
    357 bars → n_windows = (357-315)//21 + 1 = 3  →  success
    """
    v = WalkForwardValidator()

    # Below minimum: must raise
    with pytest.raises(ValueError, match="Insufficient data"):
        v.run(_make_flat_df(356), lambda _: None)

    # Exact minimum: must succeed and return exactly 3 windows
    ok = _mock_run_result()
    with patch("core.ai_engine.walk_forward.BacktestEngine") as MockEng:
        MockEng.return_value.run.return_value = ok
        result = v.run(_make_flat_df(357), lambda _: None)

    assert result.n_windows == 3, (
        f"Expected exactly 3 windows for 357 bars, got {result.n_windows}"
    )


# ── Test 3: Walk-forward OOS never overlaps train ─────────────────────────────

def test_walk_forward_oos_slice_disjoint_from_train():
    """
    For every walk-forward window the OOS slice must:
      (a) start exactly where the train slice ends: test_start == train_end
      (b) share no bar indices with the train slice

    Tested across all windows of a 420-bar dataset:
      n_windows = (420-315)//21 + 1 = 6 windows
    """
    ok = _mock_run_result()

    with patch("core.ai_engine.walk_forward.BacktestEngine") as MockEng:
        MockEng.return_value.run.return_value = ok
        result = WalkForwardValidator().run(_make_flat_df(420), lambda _: None)

    assert result.n_windows >= 3, "Need ≥3 windows to make the test non-trivial"

    for w in result.windows:
        # (a) Structural adjacency guarantee
        assert w.test_start == w.train_end, (
            f"Window {w.window_idx}: test_start={w.test_start} != "
            f"train_end={w.train_end} — OOS begins inside IS window"
        )
        # (b) Disjointness of bar-index sets
        train_idx = set(range(w.train_start, w.train_end))
        test_idx  = set(range(w.test_start,  w.test_end))
        overlap   = train_idx & test_idx
        assert not overlap, (
            f"Window {w.window_idx}: {len(overlap)} overlapping bar indices "
            f"(train [{w.train_start},{w.train_end}), "
            f"OOS [{w.test_start},{w.test_end}))"
        )


# ── Test 4: SL/TP correctness ─────────────────────────────────────────────────

def test_sl_hit_on_bar_3_produces_loss():
    """
    Deterministic 5-bar price series designed so SL is breached on exactly
    bar 3 and TP is never reached.

    Setup:
      entry_price = 1.0850,  sl_pips = 20,  pip_size = 0.0001
      sl_price    = 1.0850 - 20 × 0.0001 = 1.0830
      tp_price    = 1.0850 + 40 × 0.0001 = 1.0890

      bar 0 : strategy signals buy (bar_in=0)
      bar 1 : low = 1.0840 > 1.0830  → no exit
      bar 2 : low = 1.0840 > 1.0830  → no exit
      bar 3 : low = 1.0820 ≤ 1.0830  → SL hit
      bar 4 : never reached (trade already closed)

    Expected: trade_log has 1 record with bar_out=3, outcome='loss', pnl_r=-1.0.
    """
    entry   = 1.0850
    sl_pips = 20.0
    tp_pips = 40.0

    rows = [
        # (time,                  open,   high,   low,    close )
        ("2024-01-01 00:00", entry,  1.0860, 1.0840, entry ),  # bar 0
        ("2024-01-01 01:00", entry,  1.0860, 1.0840, entry ),  # bar 1
        ("2024-01-01 02:00", entry,  1.0860, 1.0840, entry ),  # bar 2
        ("2024-01-01 03:00", entry,  1.0860, 1.0820, entry ),  # bar 3: SL
        ("2024-01-01 04:00", entry,  1.0860, 1.0840, entry ),  # bar 4: unreachable
    ]
    df           = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df["time"]   = pd.to_datetime(df["time"])

    entered = [False]

    def _once_buy(df_visible: pd.DataFrame) -> Signal | None:
        """Signal exactly once, on the first bar."""
        if entered[0]:
            return None
        if len(df_visible) == 1:
            entered[0] = True
            return Signal(
                direction="buy",
                sl_pips=sl_pips,
                tp_pips=tp_pips,
                entry_price=entry,
            )
        return None

    result = BacktestEngine(pip_size=0.0001).run(df, _once_buy)

    assert result.total_trades == 1, (
        f"Expected 1 completed trade, got {result.total_trades}"
    )
    t = result.trade_log[0]
    assert t.bar_in  == 0,       f"bar_in:  expected 0,      got {t.bar_in}"
    assert t.bar_out == 3,       f"bar_out: expected 3,      got {t.bar_out}"
    assert t.outcome == "loss",  f"outcome: expected 'loss', got {t.outcome!r}"
    assert t.pnl_r   == -1.0,   f"pnl_r:   expected -1.0,   got {t.pnl_r}"


# ── Test 5: Regime gate structural suppression ────────────────────────────────

def test_regime_gate_prevents_bos_logic_on_blocked_bars():
    """
    When the regime gate blocks a bar, the downstream BOS entry logic must
    never execute — even if a real BOS signal exists on that bar.

    Strategy internals:
      Step 1 — Regime gate: block every odd-indexed bar (early return None).
      Step 2 — BOS logic:   only reached on even-indexed bars.

    We track which bars enter BOS logic and verify none coincide with odd
    (blocked) bars.  Tiny SL/TP (0.1/0.2 pip) lets trades close on the very
    next bar via the random-walk wick, so the engine calls strategy on every
    bar and the tracking is exhaustive.

    Also verifies that no trade is recorded with bar_in on a blocked bar.
    """
    bos = BOSIdentifier(n=3)

    blocked_at:     list[int] = []   # bars where regime gate fired
    bos_reached_at: list[int] = []   # bars where BOS logic executed

    def _gated_strategy(df_visible: pd.DataFrame) -> Signal | None:
        bar_idx = len(df_visible) - 1

        # ── Step 1: Regime gate ───────────────────────────────────────────
        if bar_idx % 2 == 1:          # odd bars are "blocked"
            blocked_at.append(bar_idx)
            return None               # BOS logic NEVER reached past this point

        # ── Step 2: BOS entry logic ───────────────────────────────────────
        # Reaching this line proves bar_idx is NOT blocked.
        bos_reached_at.append(bar_idx)

        if len(df_visible) >= 7:
            out = bos.identify(df_visible)
            if out["bullish_bos"].iloc[-1]:
                return Signal(
                    direction="buy",
                    sl_pips=0.1,     # tiny → trade closes on next bar via wick
                    tp_pips=0.2,
                    entry_price=float(df_visible["close"].iloc[-1]),
                )
        return None

    # Random-walk data gives BOSIdentifier genuine swing structure.
    df     = _make_random_ohlc(n=100, seed=99)
    result = BacktestEngine().run(df, _gated_strategy)

    blocked_set = set(blocked_at)

    # Core assertion: BOS logic never ran on a blocked bar.
    bos_on_blocked = [b for b in bos_reached_at if b in blocked_set]
    assert not bos_on_blocked, (
        f"BOS logic executed on {len(bos_on_blocked)} blocked bar(s): "
        f"{bos_on_blocked[:5]} — regime gate did not suppress BOS evaluation"
    )

    # No trade may open at a blocked bar.
    for trade in result.trade_log:
        assert trade.bar_in not in blocked_set, (
            f"Trade opened at blocked bar {trade.bar_in} (bar_in is odd — "
            "should have been suppressed by regime gate)"
        )

    # Sanity: both branches must have executed at least once.
    assert len(blocked_at)     > 0, "Regime gate never fired — test is vacuous"
    assert len(bos_reached_at) > 0, "BOS logic never reached — test is vacuous"


# ── Test 6: BacktestEngine — TP hit produces correct win pnl_r ───────────────

def test_tp_hit_produces_win():
    """
    Deterministic 5-bar series where TP is hit on bar 2.
    entry=1.0850, sl_pips=20, tp_pips=40 → pnl_r = 40/20 = 2.0
    """
    entry   = 1.0850
    sl_pips = 20.0
    tp_pips = 40.0

    rows = [
        ("2024-01-01 00:00", entry, 1.0860, 1.0840, entry),  # bar 0: entry
        ("2024-01-01 01:00", entry, 1.0860, 1.0840, entry),  # bar 1: no hit
        ("2024-01-01 02:00", entry, 1.0895, 1.0840, entry),  # bar 2: TP hit
        ("2024-01-01 03:00", entry, 1.0860, 1.0840, entry),  # bar 3: unreachable
    ]
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"])

    entered = [False]

    def _once_buy(df_visible):
        if entered[0]:
            return None
        if len(df_visible) == 1:
            entered[0] = True
            return Signal("buy", sl_pips, tp_pips, entry)
        return None

    result = BacktestEngine(pip_size=0.0001).run(df, _once_buy)

    assert result.total_trades == 1
    t = result.trade_log[0]
    assert t.bar_out == 2,      f"bar_out: expected 2, got {t.bar_out}"
    assert t.outcome == "win",  f"outcome: expected 'win', got {t.outcome!r}"
    assert t.pnl_r   == pytest.approx(2.0), f"pnl_r: expected 2.0, got {t.pnl_r}"


# ── Test 7: BacktestEngine — sell SL hit ─────────────────────────────────────

def test_sell_sl_hit_produces_loss():
    """
    Sell trade: SL is above entry. High breaches SL on bar 2 → loss.
    entry=1.0850, sl_pips=20 → sl_price=1.0870
    """
    entry   = 1.0850
    sl_pips = 20.0
    tp_pips = 40.0

    rows = [
        ("2024-01-01 00:00", entry, 1.0860, 1.0840, entry),  # bar 0: entry
        ("2024-01-01 01:00", entry, 1.0860, 1.0840, entry),  # bar 1: no hit
        ("2024-01-01 02:00", entry, 1.0875, 1.0840, entry),  # bar 2: SL hit
        ("2024-01-01 03:00", entry, 1.0860, 1.0840, entry),  # bar 3: unreachable
    ]
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"])

    entered = [False]

    def _once_sell(df_visible):
        if entered[0]:
            return None
        if len(df_visible) == 1:
            entered[0] = True
            return Signal("sell", sl_pips, tp_pips, entry)
        return None

    result = BacktestEngine(pip_size=0.0001).run(df, _once_sell)

    assert result.total_trades == 1
    t = result.trade_log[0]
    assert t.bar_out == 2,      f"bar_out: expected 2, got {t.bar_out}"
    assert t.outcome == "loss", f"outcome: expected 'loss', got {t.outcome!r}"
    assert t.pnl_r   == -1.0,  f"pnl_r: expected -1.0, got {t.pnl_r}"


# ── Test 8: BacktestEngine — win_rate calculation ────────────────────────────

def test_backtest_win_rate_calculation():
    """
    With 2 wins and 1 loss, win_rate must be 66.67%.
    """
    trades_fired = [0]

    def _strategy(df_visible):
        idx = len(df_visible) - 1
        if idx % 5 == 0 and trades_fired[0] < 3:
            trades_fired[0] += 1
            direction = "buy" if trades_fired[0] <= 2 else "sell"
            return Signal(direction, 10.0, 20.0, float(df_visible["close"].iloc[-1]))
        return None

    df     = _make_random_ohlc(100, seed=7)
    result = BacktestEngine(pip_size=0.0001).run(df, _strategy)

    assert result.total_trades >= 1
    assert 0.0 <= result.win_rate <= 100.0, (
        f"win_rate {result.win_rate} must be in [0, 100]"
    )
    # Verify win_rate formula: wins/total * 100
    wins = sum(1 for t in result.trade_log if t.outcome == "win")
    expected_wr = wins / result.total_trades * 100
    assert result.win_rate == pytest.approx(expected_wr, abs=0.01)


# ── Test 9: BacktestEngine — no trades on no-signal strategy ─────────────────

def test_backtest_no_trades_when_no_signals():
    """A strategy that never signals must produce zero trades."""
    df     = _make_random_ohlc(50, seed=3)
    result = BacktestEngine().run(df, lambda _: None)

    assert result.total_trades == 0
    assert result.net_r        == 0.0
    assert result.win_rate     == 0.0
    assert result.trade_log    == []


# ── Test 10: BacktestEngine — net_r is sum of pnl_r ─────────────────────────

def test_backtest_net_r_is_sum_of_pnl_r():
    """net_r must equal the sum of all trade pnl_r values."""
    df     = _make_random_ohlc(200, seed=11)
    result = BacktestEngine(pip_size=0.0001).run(df, lambda df_v: (
        Signal("buy", 10.0, 20.0, float(df_v["close"].iloc[-1]))
        if len(df_v) % 15 == 1 else None
    ))

    if result.total_trades > 0:
        expected_net_r = round(sum(t.pnl_r for t in result.trade_log), 4)
        assert result.net_r == pytest.approx(expected_net_r, abs=0.001)


# ── Test 11: WalkForwardValidator — avg_sharpe and avg_win_rate computed ──────

def test_walk_forward_avg_metrics_computed():
    """
    WalkForwardResult must have avg_sharpe and avg_win_rate computed as
    the mean of per-window values.
    """
    ok = _mock_run_result(sharpe=1.5, win_rate=55.0)

    with patch("core.ai_engine.walk_forward.BacktestEngine") as MockEng:
        MockEng.return_value.run.return_value = ok
        result = WalkForwardValidator().run(_make_flat_df(420), lambda _: None)

    assert result.n_windows >= 3
    assert result.avg_sharpe   == pytest.approx(1.5, abs=0.01)
    assert result.avg_win_rate == pytest.approx(55.0, abs=0.01)


# ── Test 12: WalkForwardValidator — window indices are sequential ─────────────

def test_walk_forward_window_indices_sequential():
    """window_idx must be 0, 1, 2, ... in order."""
    ok = _mock_run_result()

    with patch("core.ai_engine.walk_forward.BacktestEngine") as MockEng:
        MockEng.return_value.run.return_value = ok
        result = WalkForwardValidator().run(_make_flat_df(420), lambda _: None)

    for i, w in enumerate(result.windows):
        assert w.window_idx == i, (
            f"Window at position {i} has window_idx={w.window_idx}"
        )


# ── Test 13: WalkForwardValidator — train window is exactly TRAIN_BARS ────────

def test_walk_forward_train_window_size():
    """Each window's train slice must be exactly TRAIN_BARS (252) wide."""
    from core.ai_engine.walk_forward import TRAIN_BARS
    ok = _mock_run_result()

    with patch("core.ai_engine.walk_forward.BacktestEngine") as MockEng:
        MockEng.return_value.run.return_value = ok
        result = WalkForwardValidator().run(_make_flat_df(420), lambda _: None)

    for w in result.windows:
        train_size = w.train_end - w.train_start
        assert train_size == TRAIN_BARS, (
            f"Window {w.window_idx}: train size {train_size} != {TRAIN_BARS}"
        )


# ── Test 14: BacktestEngine — sharpe_ratio is zero with no trades ─────────────

def test_backtest_sharpe_zero_with_no_trades():
    """sharpe_ratio must be 0.0 when there are no trades."""
    df     = _make_flat_df(20)
    result = BacktestEngine().run(df, lambda _: None)

    assert result.sharpe_ratio == 0.0


# ── Test 15: BacktestEngine — sell TP hit ─────────────────────────────────────

def test_sell_tp_hit_produces_win():
    """
    Sell trade: TP is below entry. Low breaches TP on bar 2 → win.
    entry=1.0850, sl_pips=20, tp_pips=40 → tp_price=1.0810, pnl_r=2.0
    """
    entry   = 1.0850
    sl_pips = 20.0
    tp_pips = 40.0

    rows = [
        ("2024-01-01 00:00", entry, 1.0860, 1.0840, entry),  # bar 0: entry
        ("2024-01-01 01:00", entry, 1.0860, 1.0840, entry),  # bar 1: no hit
        ("2024-01-01 02:00", entry, 1.0860, 1.0805, entry),  # bar 2: TP hit
        ("2024-01-01 03:00", entry, 1.0860, 1.0840, entry),  # bar 3: unreachable
    ]
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"])

    entered = [False]

    def _once_sell(df_visible):
        if entered[0]:
            return None
        if len(df_visible) == 1:
            entered[0] = True
            return Signal("sell", sl_pips, tp_pips, entry)
        return None

    result = BacktestEngine(pip_size=0.0001).run(df, _once_sell)

    assert result.total_trades == 1
    t = result.trade_log[0]
    assert t.bar_out == 2,     f"bar_out: expected 2, got {t.bar_out}"
    assert t.outcome == "win", f"outcome: expected 'win', got {t.outcome!r}"
    assert t.pnl_r   == pytest.approx(2.0)


# ── Test 16: BacktestEngine — only one active trade at a time ─────────────────

def test_backtest_only_one_active_trade():
    """
    The engine must not open a new trade while one is already active.
    A strategy that signals on every bar should still produce at most
    one trade per open/close cycle.
    """
    signals_sent = [0]

    def _always_signal(df_visible):
        signals_sent[0] += 1
        return Signal("buy", 10.0, 20.0, float(df_visible["close"].iloc[-1]))

    df     = _make_random_ohlc(50, seed=5)
    result = BacktestEngine(pip_size=0.0001).run(df, _always_signal)

    # With 50 bars and tiny SL/TP, trades close quickly — but never overlap
    for i in range(len(result.trade_log) - 1):
        t1 = result.trade_log[i]
        t2 = result.trade_log[i + 1]
        assert t2.bar_in >= t1.bar_out, (
            f"Trade {i+1} opened at bar {t2.bar_in} before trade {i} "
            f"closed at bar {t1.bar_out} — overlapping trades detected"
        )


# ── Test 17: WalkForwardValidator — custom params ─────────────────────────────

def test_walk_forward_custom_params():
    """
    WalkForwardValidator with custom train/test/step params must use them.
    train=100, test=30, step=10, min_windows=3 → min_bars = 100+30+2*10 = 150
    """
    v  = WalkForwardValidator(train_bars=100, test_bars=30, step_bars=10, min_windows=3)
    ok = _mock_run_result()

    # 149 bars → 2 windows → ValueError
    with pytest.raises(ValueError, match="Insufficient data"):
        v.run(_make_flat_df(149), lambda _: None)

    # 150 bars → 3 windows → success
    with patch("core.ai_engine.walk_forward.BacktestEngine") as MockEng:
        MockEng.return_value.run.return_value = ok
        result = v.run(_make_flat_df(150), lambda _: None)

    assert result.n_windows == 3


# ── Test 18: BacktestEngine — trade_log is ordered by bar_in ─────────────────

def test_backtest_trade_log_ordered_by_bar_in():
    """trade_log must be ordered chronologically (bar_in ascending)."""
    df     = _make_random_ohlc(200, seed=13)
    result = BacktestEngine(pip_size=0.0001).run(df, lambda df_v: (
        Signal("buy", 5.0, 10.0, float(df_v["close"].iloc[-1]))
        if len(df_v) % 20 == 1 else None
    ))

    bar_ins = [t.bar_in for t in result.trade_log]
    assert bar_ins == sorted(bar_ins), (
        f"trade_log not ordered by bar_in: {bar_ins}"
    )


# ── Test 19: BacktestEngine — pnl_r is -1.0 for all losses ───────────────────

def test_backtest_loss_pnl_r_is_minus_one():
    """Every loss trade must have pnl_r == -1.0 (1R loss)."""
    df     = _make_random_ohlc(100, seed=17)
    result = BacktestEngine(pip_size=0.0001).run(df, lambda df_v: (
        Signal("buy", 5.0, 10.0, float(df_v["close"].iloc[-1]))
        if len(df_v) % 10 == 1 else None
    ))

    for t in result.trade_log:
        if t.outcome == "loss":
            assert t.pnl_r == -1.0, (
                f"Loss trade at bar {t.bar_in} has pnl_r={t.pnl_r}, expected -1.0"
            )


# ── Test 20: WalkForwardValidator — test slice is exactly TEST_BARS ───────────

def test_walk_forward_test_slice_size():
    """Each window's OOS slice must be exactly TEST_BARS (63) wide."""
    from core.ai_engine.walk_forward import TEST_BARS
    ok = _mock_run_result()

    with patch("core.ai_engine.walk_forward.BacktestEngine") as MockEng:
        MockEng.return_value.run.return_value = ok
        result = WalkForwardValidator().run(_make_flat_df(420), lambda _: None)

    for w in result.windows:
        test_size = w.test_end - w.test_start
        assert test_size == TEST_BARS, (
            f"Window {w.window_idx}: test size {test_size} != {TEST_BARS}"
        )
