import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.config import RATE_LIMIT

# Sliding-window length (seconds) defining "per minute" for rate limiting.
WINDOW_SECONDS = 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to limit the number of API calls per client IP per minute."""

    def __init__(self, app, calls_per_minute: int | None = None):
        if calls_per_minute is None:
            calls_per_minute = RATE_LIMIT
        super().__init__(app)
        self.calls_per_minute = calls_per_minute
        self.calls_by_ip: dict[str, list[float]] = {}

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ):
        """Process each request and enforce rate limiting."""
        # Transports without a peer (e.g. unix sockets) report no client;
        # those requests share one fallback bucket instead of crashing.
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()
        cutoff_time = current_time - WINDOW_SECONDS
        recent_calls = [
            t for t in self.calls_by_ip.get(client_ip, []) if t > cutoff_time
        ]
        if len(recent_calls) >= self.calls_per_minute:
            return JSONResponse(
                {
                    "error": "Rate limit exceeded",
                    "message": f"Max {self.calls_per_minute} calls per minute",
                },
                status_code=429,
            )
        self.calls_by_ip[client_ip] = recent_calls + [current_time]
        return await call_next(request)
