# In-memory cache for API responses

import copy
import time
from datetime import datetime
from typing import Any

from core.config import CACHE_TTL

# Time-bucket width for cache keys, in minutes.
BUCKET_MINUTES = 15

# Cache key: (rounded latitude, rounded longitude, bucketed datetime).
CacheKey = tuple[float, float, str]


class SimpleCache:
    """A basic in-memory cache with TTL (time-to-live) support.

    Staleness bounds: keys bucket time to 15-minute intervals and coordinates
    to ~1 km, so requests up to 15 min / ~1 km apart share one payload while
    the Moon moves ~0.125° per 15 min. Reads return deep copies so callers can
    never mutate the stored payload (e.g. its ``meta``).
    """

    def __init__(self, ttl_seconds: int | None = None):
        if ttl_seconds is None:
            ttl_seconds = CACHE_TTL
        self.ttl = ttl_seconds
        self.entries: dict[CacheKey, tuple[dict[str, Any], float]] = {}

    def _get_key(self, lat: float, lon: float, dt: datetime) -> CacheKey:
        bucket = (dt.minute // BUCKET_MINUTES) * BUCKET_MINUTES
        rounded_dt = dt.replace(minute=bucket, second=0, microsecond=0)
        return (round(lat, 2), round(lon, 2), rounded_dt.isoformat())

    def get(self, lat: float, lon: float, dt: datetime) -> dict[str, Any] | None:
        """Retrieve a cached value if it exists and is not expired."""
        key = self._get_key(lat, lon, dt)
        if key in self.entries:
            data, timestamp = self.entries[key]
            if time.time() - timestamp < self.ttl:
                # Deep copy: callers must not mutate the stored payload.
                return copy.deepcopy(data)
            else:
                del self.entries[key]
        return None

    def set(self, lat: float, lon: float, dt: datetime, data: dict[str, Any]):
        """Store a value in the cache with the current timestamp."""
        key = self._get_key(lat, lon, dt)
        self.entries[key] = (data, time.time())
