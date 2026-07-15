from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class GlobalApiRateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._app = app
        self._limit = requests_per_minute
        self._now = now
        self._requests: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self._app(scope, receive, send)
            return

        retry_after = await self._retry_after()
        if retry_after is not None:
            response = JSONResponse(
                status_code=429,
                content={"detail": "The public demo request limit has been reached."},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)

    async def _retry_after(self) -> int | None:
        async with self._lock:
            now = self._now()
            cutoff = now - 60
            while self._requests and self._requests[0] <= cutoff:
                self._requests.popleft()
            if len(self._requests) >= self._limit:
                return max(1, int(60 - (now - self._requests[0])) + 1)
            self._requests.append(now)
            return None
