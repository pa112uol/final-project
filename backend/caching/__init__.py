"""Redis-backed caching and rate limiting.

Every entry point degrades to a no-op when REDIS_URL is unset or the server is
unreachable, so the backend runs unchanged without Redis.
"""

from .async_cache import AsyncRedisCache, get_async_cache, set_async_cache
from .config import cache_enabled, redis_url
from .keys import build_key
from .local import BoundedTTLCache, FallbackCache, get_view_cache, set_view_cache
from .ratelimit import RedisRateLimiter
from .sync_cache import SyncRedisCache, get_sync_cache, set_sync_cache

__all__ = [
    "AsyncRedisCache",
    "BoundedTTLCache",
    "FallbackCache",
    "RedisRateLimiter",
    "SyncRedisCache",
    "build_key",
    "cache_enabled",
    "get_async_cache",
    "get_sync_cache",
    "get_view_cache",
    "redis_url",
    "set_async_cache",
    "set_sync_cache",
    "set_view_cache",
]
