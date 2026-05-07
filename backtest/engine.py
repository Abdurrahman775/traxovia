"""backtest/engine.py — Event-driven backtester with SL/TP simulation."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional
import pandas as pd


@dataclass
class Signal:
    direction:   str
    sl_pips:     float
    tp_pips:     float
    entry_price: float


@dataclass
class TradeRecord:
    bar_in:  int
    bar_out: int
    outcome: str   # 'win' | 'loss'
    pnl_r:   float


@dataclass
class BacktestResult:
    total_trades: int
    net_r:        float
    win_rate:     float
    sharpe_ratio: float
    trade_log:    list[TradeRecord] = field(default_factory=list)


class BacktestEngine:
    def __init__(self, pip_size: float = 0.0001):
        self.pip_size = pip_size

    def run(
        self,
        df: pd.DataFrame,
        strategy: Callable[[pd.DataFrame], Optional[Signal]],
    ) -> BacktestResult:
        trades: list[TradeRecord] = []
        active: Optional[tuple] = None  # (bar_in, signal, sl_price, tp_price)

        for i in range(len(df)):
            bar = df.iloc[i]

            if active is not None:
                bar_in, sig, sl_price, tp_price = active
                low  = float(bar["low"])
                high = float(bar["high"])

                if sig.direction == "buy":
                    if low <= sl_price:
                        trades.append(TradeRecord(bar_in, i, "loss", -1.0))
                        active = None
                        continue
                    if high >= tp_price:
                        rr = sig.tp_pips / sig.sl_pips
                        trades.append(TradeRecord(bar_in, i, "win", round(rr, 2)))
                        active = None
                        continue
                else:  # sell
                    if high >= sl_price:
                        trades.append(TradeRecord(bar_in, i, "loss", -1.0))
                        active = None
                        continue
                    if low <= tp_price:
                        rr = sig.tp_pips / sig.sl_pips
                        trades.append(TradeRecord(bar_in, i, "win", round(rr, 2)))
                        active = None
                        continue

            if active is None:
                sig = strategy(df.iloc[: i + 1])
                if sig is not None:
                    if sig.direction == "buy":
                        sl_price = sig.entry_price - sig.sl_pips * self.pip_size
                        tp_price = sig.entry_price + sig.tp_pips * self.pip_size
                    else:
                        sl_price = sig.entry_price + sig.sl_pips * self.pip_size
                        tp_price = sig.entry_price - sig.tp_pips * self.pip_size
                    active = (i, sig, sl_price, tp_price)

        total  = len(trades)
        net_r  = sum(t.pnl_r for t in trades)
        wins   = sum(1 for t in trades if t.outcome == "win")
        wr     = (wins / total * 100) if total > 0 else 0.0

        if total > 1:
            mean_r = net_r / total
            variance = sum((t.pnl_r - mean_r) ** 2 for t in trades) / (total - 1)
            std_r = variance ** 0.5
            sharpe = (mean_r / std_r) if std_r > 0 else 0.0
        else:
            sharpe = 0.0

        return BacktestResult(
            total_trades=total,
            net_r=round(net_r, 4),
            win_rate=round(wr, 2),
            sharpe_ratio=round(sharpe, 4),
            trade_log=trades,
        )
