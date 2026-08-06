# Synchronous cache implementation, used by the Django views

import uuid

import redis

from .base import BaseCache
from .config import CONNECT_TIMEOUT_S, SOCKET_TIMEOUT_S, redis_url

_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def _default_connect():
    return redis.Redis.from_url(
        redis_url(),
        socket_connect_timeout=CONNECT_TIMEOUT_S,
        socket_timeout=SOCKET_TIMEOUT_S,
        decode_responses=True,
    )


class SyncRedisCache(BaseCache):
    def __init__(self, connect=_default_connect, enabled=None):
        super().__init__(connect, enabled=enabled, name="sync")
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = self._connect()
        return self._client

    # Returns the decoded value, or None for a miss, a decode failure or an
    # unreachable Redis
    def get_json(self, key: str):
        if not self._available():
            return None
        try:
            raw = self._get_client().get(key)
            self._on_success()
        except redis.RedisError as exc:
            self._on_failure(exc)
            return None
        return self._decode(raw)

    def set_json(self, key: str, value: object, ttl: int) -> bool:
        if not self._available():
            return False
        encoded = self._encode(value)
        if encoded is None:
            return False
        try:
            self._get_client().set(key, encoded, ex=ttl)
            self._on_success()
            return True
        except redis.RedisError as exc:
            self._on_failure(exc)
            return False

    def delete(self, key: str) -> bool:
        if not self._available():
            return False
        try:
            self._get_client().delete(key)
            self._on_success()
            return True
        except redis.RedisError as exc:
            self._on_failure(exc)
            return False

    # Acquires a short-lived distributed lock, so only one worker recomputes an
    # expired key. Returns an ownership token, or None when another worker holds
    # it: that caller serves stale data rather than running the same expensive
    # refresh in parallel. The token has to be passed back to release_lock
    def acquire_lock(self, key: str, ttl: int) -> str | None:
        if not self._available():
            return None
        token = uuid.uuid4().hex
        try:
            acquired = self._get_client().set(key, token, nx=True, ex=ttl)
            self._on_success()
            return token if acquired else None
        except redis.RedisError as exc:
            self._on_failure(exc)
            return None

    # Releases a lock acquired with acquire_lock. The token has to match the
    # one stored in Redis, otherwise the lock is not released
    def release_lock(self, key: str, token: str | None) -> None:
        if not token or not self._available():
            return
        try:
            self._get_client().eval(_RELEASE_LOCK_SCRIPT, 1, key, token)
            self._on_success()
        except redis.RedisError as exc:
            self._on_failure(exc)


_cache: SyncRedisCache | None = None


def get_sync_cache() -> SyncRedisCache:
    global _cache
    if _cache is None:
        _cache = SyncRedisCache()
    return _cache


# Swap in a fakeredis-backed cache, or pass None to restore the
# default. Kept here so tests never have to reach into module globals.
def set_sync_cache(cache: SyncRedisCache | None) -> None:
    global _cache
    _cache = cache
