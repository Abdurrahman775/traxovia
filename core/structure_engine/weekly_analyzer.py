"""core/structure_engine/weekly_analyzer.py — Weekly HTF bias from W1 data."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class WeeklyAnalyzer:
    def __init__(self, pool=None, redis=None):
        self.pool  = pool
        self.redis = redis

    async def get_bias(self, symbol: str) -> str | None:
        if self.redis:
            try:
                cached = await self.redis.get(f"weekly_bias:{symbol}")
                if cached is not None:
                    val = cached.decode() if isinstance(cached, bytes) else cached
                    if val in ("bullish", "bearish"):
                        return val
            except Exception:
                pass

        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT open, close FROM ohlc_w1
                           WHERE symbol=$1 ORDER BY time DESC LIMIT 4""",
                        symbol,
                    )
                    if rows:
                        o = float(rows[0]["open"])
                        c = float(rows[0]["close"])
                        if c > o:
                            return "bullish"
                        if c < o:
                            return "bearish"
            except Exception as exc:
                logger.debug("WeeklyAnalyzer DB fallback failed for %s: %s", symbol, exc)

        return None
