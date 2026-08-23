"""
Lightweight in-memory, per-IP sliding-window rate limiter.

This is intentionally simple (no Redis dependency) so the project runs
as a single container on Render. It is enough to demonstrate and test
the DoS-mitigation control described in Section 3.6.4 ("lightweight
rate checks inline"). For a multi-instance deployment you would move
this state to Redis.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from app.config import settings


class RateLimiter:
    def __init__(self, window_seconds: int, max_requests: int):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        q = self._hits[key]
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        if len(q) >= self.max_requests:
            return False
        q.append(now)
        return True

    def reset(self):
        self._hits.clear()


rate_limiter = RateLimiter(
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    max_requests=settings.RATE_LIMIT_MAX_REQUESTS,
)
