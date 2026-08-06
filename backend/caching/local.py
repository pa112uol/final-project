# In-process cache used when Redis is unavailable.

import threading
import time
from collections import OrderedDict

DEFAULT_MAX_ENTRIES = 5_000


# A time-to-live cache with a bounded size
class BoundedTTLCache:
    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES):
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[object, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def set(self, key: str, value: object, ttl: int) -> None:
        with self._lock:
            self._entries[key] = (value, time.monotonic() + ttl)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# A cache-lifetime signal
LOCAL_SLOT_TOKEN = "local"


# A cache that uses a primary cache (Redis) when it is healthy and
# falls back to an in-process cache when it is not
class FallbackCache:

    def __init__(self, primary, local: BoundedTTLCache | None = None):
        self._primary = primary
        self._local = local if local is not None else BoundedTTLCache()

    # Returns the value from the primary cache if it is healthy, otherwise from the
    # local cache
    def get_json(self, key: str):
        if self._primary.is_healthy:
            value = self._primary.get_json(key)
            if value is not None:
                return value
            if self._primary.is_healthy:
                return None
        return self._local.get(key)

    # Falls through to the local tier whenever the primary write did not land,
    # so the value the caller just computed is not simply dropped
    def set_json(self, key: str, value: object, ttl: int) -> bool:
        if self._primary.is_healthy:
            if self._primary.set_json(key, value, ttl):
                return True
        self._local.set(key, value, ttl)
        return True

    # Deletes from both tiers: either may hold the entry after a failover, and
    # a delete that only clears the healthy one leaves the other to resurface
    def delete(self, key: str) -> bool:
        if self._primary.is_healthy:
            self._primary.delete(key)
        self._local.delete(key)
        return True

    # Returns an ownership token to pass back to release_refresh_slot, or None
    # when another worker holds the slot
    def acquire_refresh_slot(self, key: str, ttl: int) -> str | None:
        if self._primary.is_healthy:
            return self._primary.acquire_lock(key, ttl)
        return LOCAL_SLOT_TOKEN

    def release_refresh_slot(self, key: str, token: str | None) -> None:
        if token and token != LOCAL_SLOT_TOKEN and self._primary.is_healthy:
            self._primary.release_lock(key, token)

    def clear_local(self) -> None:
        self._local.clear()


_view_cache: FallbackCache | None = None


def get_view_cache() -> FallbackCache:
    global _view_cache
    if _view_cache is None:
        from .sync_cache import get_sync_cache

        _view_cache = FallbackCache(get_sync_cache())
    return _view_cache


def set_view_cache(cache: FallbackCache | None) -> None:
    global _view_cache
    _view_cache = cache
