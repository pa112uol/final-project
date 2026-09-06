# Distributed rate limiting for MusicBrainz

import logging

from .async_cache import get_async_cache
from .config import KEY_PREFIX

logger = logging.getLogger(__name__)

MB_SLOT_KEY = f"{KEY_PREFIX}ratelimit:musicbrainz"

SLOT_KEY_TTL_MS = 60_000

# Next-slot reservation in the style of the GCRA / virtual-scheduling rate
# limiters in the Redis rate-limiting patterns, using Redis TIME as the clock
# so no worker depends on a synchronised local one
# https://redis.io/docs/latest/develop/use-cases/patterns/
_RESERVE_SLOT_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local next_at = tonumber(redis.call('GET', KEYS[1]) or '0')
local slot = math.max(now_ms, next_at)
redis.call('SET', KEYS[1], slot + tonumber(ARGV[1]), 'PX', tonumber(ARGV[2]))
return slot - now_ms
"""


class RedisRateLimiter:
    def __init__(self, key: str, interval_s: float, cache=None):
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        self._key = key
        self._interval_ms = int(interval_s * 1000)
        self._cache = cache

    def _get_cache(self):
        return self._cache if self._cache is not None else get_async_cache()

    # Reserves the next slot, returning the wait in seconds, or None if Redis is
    # down (caller must then fall back to in-process limiting, not skip waiting).
    # The slot is spent on reservation even if the caller drops it, so a retry
    # waits out a fresh interval
    async def reserve(self) -> float | None:
        wait_ms = await self._get_cache().eval_script(
            _RESERVE_SLOT_SCRIPT,
            [self._key],
            [self._interval_ms, SLOT_KEY_TTL_MS],
        )
        if wait_ms is None:
            return None
        try:
            return max(0.0, float(wait_ms) / 1000.0)
        except (TypeError, ValueError):
            logger.warning(
                "[ratelimit] unexpected slot reservation result: %r", wait_ms
            )
            return None
