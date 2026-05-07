"""
api/middleware/rate_limit.py — In-memory sliding-window rate limiter.

Applied to auth endpoints to prevent brute-force attacks.
Uses a per-IP sliding window stored in a dict (suitable for single-process deployments).
For multi-process deployments, replace with a Redis-backed counter.
"""
import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request, status


# {ip: deque of timestamps}
_windows: dict[str, deque] = defaultdict(deque)

# Default limits — override per-route via the factory
_DEFAULT_LIMIT = 20       # max requests
_DEFAULT_WINDOW = 60      # per seconds


def rate_limit(limit: int = _DEFAULT_LIMIT, window: int = _DEFAULT_WINDOW):
    """
    FastAPI dependency factory for rate limiting by client IP.

    Usage:
        @router.post("/login")
        async def login(request: Request, _=Depends(rate_limit(limit=5, window=60))):
            ...
    """
    async def _check(request: Request):
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        q = _windows[ip]

        # Evict timestamps outside the window
        while q and q[0] < now - window:
            q.popleft()

        if len(q) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Retry after {window} seconds.",
                headers={"Retry-After": str(window)},
            )

        q.append(now)

    return _check
