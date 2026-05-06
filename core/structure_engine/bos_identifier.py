"""core/structure_engine/bos_identifier.py — Break of Structure detection."""
from __future__ import annotations

import pandas as pd


class BOSIdentifier:
    """Detect bullish/bearish Break-of-Structure events on OHLC data.

    A swing high/low at index j is confirmed once n bars have elapsed after it.
    Bullish BOS = first close above the most recently confirmed swing high.
    Bearish BOS = first close below the most recently confirmed swing low.
    """

    def __init__(self, n: int = 3):
        self.n = n

    def identify(self, df: pd.DataFrame) -> pd.DataFrame:
        n = self.n
        result = df.copy()
        result["bullish_bos"] = False
        result["bearish_bos"] = False

        highs  = df["high"].values
        lows   = df["low"].values
        closes = df["close"].values
        length = len(df)

        last_sh: float | None = None
        last_sl: float | None = None
        sh_broken = False
        sl_broken = False

        for i in range(length):
            j = i - n
            if j >= n:
                window_hi = highs[j - n: j + n + 1]
                if highs[j] >= window_hi.max():
                    if last_sh is None or highs[j] != last_sh:
                        last_sh   = highs[j]
                        sh_broken = False

                window_lo = lows[j - n: j + n + 1]
                if lows[j] <= window_lo.min():
                    if last_sl is None or lows[j] != last_sl:
                        last_sl   = lows[j]
                        sl_broken = False

            if last_sh is not None and not sh_broken and closes[i] > last_sh:
                result.iat[i, result.columns.get_loc("bullish_bos")] = True
                sh_broken = True

            if last_sl is not None and not sl_broken and closes[i] < last_sl:
                result.iat[i, result.columns.get_loc("bearish_bos")] = True
                sl_broken = True

        return result
