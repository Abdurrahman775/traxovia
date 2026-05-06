"""core/ai_engine/walk_forward.py — Walk-forward validation."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
import pandas as pd

from backtest.engine import BacktestEngine, Signal

TRAIN_BARS = 252
TEST_BARS  = 63
STEP_BARS  = 21
MIN_WINDOWS = 3


@dataclass
class WindowResult:
    window_idx:  int
    train_start: int
    train_end:   int
    test_start:  int
    test_end:    int
    sharpe:      float
    win_rate:    float


@dataclass
class WalkForwardResult:
    n_windows:   int
    avg_sharpe:  float
    avg_win_rate: float
    windows:     list[WindowResult] = field(default_factory=list)


class WalkForwardValidator:
    def __init__(
        self,
        train_bars: int = TRAIN_BARS,
        test_bars:  int = TEST_BARS,
        step_bars:  int = STEP_BARS,
        min_windows: int = MIN_WINDOWS,
        pip_size:   float = 0.0001,
    ):
        self.train_bars  = train_bars
        self.test_bars   = test_bars
        self.step_bars   = step_bars
        self.min_windows = min_windows
        self.pip_size    = pip_size

    def run(
        self,
        df: pd.DataFrame,
        strategy: Callable[[pd.DataFrame], Optional[Signal]],
    ) -> WalkForwardResult:
        n = len(df)
        min_bars = self.train_bars + self.test_bars + (self.min_windows - 1) * self.step_bars
        n_windows = (n - self.train_bars - self.test_bars) // self.step_bars + 1

        if n_windows < self.min_windows:
            raise ValueError(
                f"Insufficient data: {n} bars yields {n_windows} windows "
                f"(minimum {self.min_windows}). Need at least {min_bars} bars."
            )

        engine  = BacktestEngine(pip_size=self.pip_size)
        windows = []

        for i in range(n_windows):
            train_start = i * self.step_bars
            train_end   = train_start + self.train_bars
            test_start  = train_end
            test_end    = test_start + self.test_bars

            if test_end > n:
                break

            test_df = df.iloc[test_start:test_end].reset_index(drop=True)
            result  = engine.run(test_df, strategy)

            windows.append(WindowResult(
                window_idx=i,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                sharpe=result.sharpe_ratio,
                win_rate=result.win_rate,
            ))

        avg_sharpe  = sum(w.sharpe   for w in windows) / len(windows) if windows else 0.0
        avg_win_rate = sum(w.win_rate for w in windows) / len(windows) if windows else 0.0

        return WalkForwardResult(
            n_windows=len(windows),
            avg_sharpe=round(avg_sharpe, 4),
            avg_win_rate=round(avg_win_rate, 2),
            windows=windows,
        )
