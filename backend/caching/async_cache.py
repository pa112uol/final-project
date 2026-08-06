# Asynchronous cache implementation, used by the pipeline client wrapper and the
# MusicBrainz rate limiter.

import asyncio
import logging
import threading

from redis import RedisError
from redis import asyncio as aioredis

from .base import BaseCache
from .config import CONNECT_TIMEOUT_S, SOCKET_TIMEOUT_S, redis_url

logger = logging.getLogger(__name__)

_NO_LOOP = object()


def _default_connect():
    return aioredis.Redis.from_url(
        redis_url(),
        socket_connect_timeout=CONNECT_TIMEOUT_S,
        socket_timeout=SOCKET_TIMEOUT_S,
        decode_responses=True,
    )


def _current_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return _NO_LOOP


class AsyncRedisCache(BaseCache):
    def __init__(self, connect=_default_connect, enabled=None):
        super().__init__(connect, enabled=enabled, name="async")
        # One client, and so one connection pool, per event loop
        self._clients: dict[object, aioredis.Redis] = {}
        self._lock = threading.Lock()

    def _get_client(self):
        loop = _current_loop()
        with self._lock:
            self._drop_finished_loops()
            client = self._clients.get(loop)
            if client is None:
                client = self._connect()
                self._clients[loop] = client
            return client

    # A closed loop's client can never be used again and its pool cannot be
    # awaited shut on a dead loop, so the entry is dropped and left to the
    # garbage collector. Caller holds the lock
    def _drop_finished_loops(self) -> None:
        for loop in list(self._clients):
            if loop is not _NO_LOOP and loop.is_closed():
                del self._clients[loop]

    # Closes the client belonging to the running loop
    async def aclose(self) -> None:
        loop = _current_loop()
        with self._lock:
            client = self._clients.pop(loop, None)
        if client is None:
            return
        try:
            await client.aclose()
        except (RedisError, RuntimeError) as exc:
            logger.debug("[cache:%s] error closing client: %s", self._name, exc)

    async def get_json(self, key: str):
        if not self._available():
            return None
        try:
            raw = await self._get_client().get(key)
            self._on_success()
        except RedisError as exc:
            self._on_failure(exc)
            return None
        return self._decode(raw)

    # Fetches several keys in one round trip. Used for the per MBID artist
    # popularity lookups where issuing one GET per MBID would replace a single
    # batched HTTP call with dozens of sequential Redis calls
    async def get_many_json(self, keys: list[str]) -> dict:
        if not self._available() or not keys:
            return {}
        try:
            raw_values = await self._get_client().mget(keys)
            self._on_success()
        except RedisError as exc:
            self._on_failure(exc)
            return {}
        decoded = {}
        for key, raw in zip(keys, raw_values):
            if raw is not None:
                decoded[key] = self._decode(raw)
        return decoded

    async def set_json(self, key: str, value: object, ttl: int) -> bool:
        if not self._available():
            return False
        encoded = self._encode(value)
        if encoded is None:
            return False
        try:
            await self._get_client().set(key, encoded, ex=ttl)
            self._on_success()
            return True
        except RedisError as exc:
            self._on_failure(exc)
            return False

    # Writes several entries in one pipeline round trip, mirroring
    # get_many_json. Entries map key to (value, ttl) so callers can mix TTLs,
    # which matters when some results in a batch are empty
    async def set_many_json(self, entries: dict) -> bool:
        if not self._available() or not entries:
            return False
        try:
            pipe = self._get_client().pipeline(transaction=False)
            for key, (value, ttl) in entries.items():
                encoded = self._encode(value)
                if encoded is not None:
                    pipe.set(key, encoded, ex=ttl)
            await pipe.execute()
            self._on_success()
            return True
        except RedisError as exc:
            self._on_failure(exc)
            return False

    async def delete(self, key: str) -> bool:
        if not self._available():
            return False
        try:
            await self._get_client().delete(key)
            self._on_success()
            return True
        except RedisError as exc:
            self._on_failure(exc)
            return False

    # Runs a Lua script server-side. Exposed for the rate limiter.
    # Returns None when Redis is unavailable so the caller can
    # fall back to in-process limiting
    async def eval_script(self, script: str, keys: list[str], args: list):
        if not self._available():
            return None
        try:
            result = await self._get_client().eval(
                script, len(keys), *keys, *args
            )
            self._on_success()
            return result
        except RedisError as exc:
            self._on_failure(exc)
            return None


_cache: AsyncRedisCache | None = None


def get_async_cache() -> AsyncRedisCache:
    global _cache
    if _cache is None:
        _cache = AsyncRedisCache()
    return _cache


# Test seam, mirroring set_sync_cache.
def set_async_cache(cache: AsyncRedisCache | None) -> None:
    global _cache
    _cache = cache
