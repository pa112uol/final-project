import asyncio
import threading
import time

import fakeredis
import pytest
from redis import ConnectionError as RedisConnectionError

from caching.async_cache import AsyncRedisCache
from caching.circuit import CircuitBreaker
from caching.local import AsyncFallbackCache, BoundedTTLCache, FallbackCache
from caching.serialization import SerializationError, dumps, loads
from caching.sync_cache import SyncRedisCache


def _enabled():
    return True


def _disabled():
    return False


@pytest.fixture
def sync_cache(fake_redis):
    return SyncRedisCache(
        connect=lambda: fakeredis.FakeRedis(
            server=fake_redis, decode_responses=True
        ),
        enabled=_enabled,
    )


@pytest.fixture
def async_cache(fake_redis):
    return AsyncRedisCache(
        connect=lambda: fakeredis.FakeAsyncRedis(
            server=fake_redis, decode_responses=True
        ),
        enabled=_enabled,
    )


def _broken_connect():
    raise RedisConnectionError("connection refused")


class _BrokenClient:
    def __getattr__(self, name):
        def _fail(*args, **kwargs):
            raise RedisConnectionError("connection refused")

        return _fail


async def _touch_cache(cache):
    await cache.set_json("k", {"v": 1}, ttl=60)


class _FlakyCache:
    # A cache that can be toggled to fail all operations,
    # to test the fallback tier
    def __init__(self, fail: bool = False):
        self.fail = fail
        self._tripped = False
        self._entries: dict[str, object] = {}

    @property
    def is_healthy(self) -> bool:
        return not self._tripped

    def heal(self) -> None:
        self._tripped = False

    def _record(self, failed: bool) -> bool:
        self._tripped = failed
        return not failed

    def get_json(self, key: str):
        if not self._record(self.fail):
            return None
        return self._entries.get(key)

    def set_json(self, key: str, value: object, ttl: int) -> bool:
        if not self._record(self.fail):
            return False
        self._entries[key] = value
        return True

    def delete(self, key: str) -> bool:
        if not self._record(self.fail):
            return False
        self._entries.pop(key, None)
        return True


class TestSerialization:
    def test_round_trips_a_dict(self):
        assert loads(dumps({"a": 1, "b": [1, 2]})) == {"a": 1, "b": [1, 2]}

    @pytest.mark.parametrize("value", [[], "", 0, None, False, {"x": None}])
    def test_round_trips_falsy_values(self, value):
        assert loads(dumps(value)) == value

    def test_flattens_a_dataclass(self):
        from recommendations.types import StreamingLinks

        links = StreamingLinks(
            apple_music="a", preview="p", youtube_video_id="y", spotify="s"
        )
        assert loads(dumps(links))["youtube_video_id"] == "y"

    def test_rejects_unencodable_values(self):
        with pytest.raises(SerializationError):
            dumps(object())

    # A corrupted or old format entry has to read as a miss so the value is
    # rebuilt, rather than raising into the request that asked for it
    @pytest.mark.parametrize("raw", ["{not json", "", None])
    def test_malformed_payloads_decode_to_none(self, raw):
        assert loads(raw) is None


class TestSyncCache:
    def test_miss_returns_none(self, sync_cache):
        assert sync_cache.get_json("nope") is None

    def test_set_then_get_round_trips(self, sync_cache):
        sync_cache.set_json("k", {"v": [1, 2]}, ttl=60)
        assert sync_cache.get_json("k") == {"v": [1, 2]}

    def test_ttl_is_applied(self, sync_cache):
        sync_cache.set_json("k", {"v": 1}, ttl=42)
        assert 0 < sync_cache._get_client().ttl("k") <= 42

    def test_delete_removes_the_entry(self, sync_cache):
        sync_cache.set_json("k", {"v": 1}, ttl=60)
        sync_cache.delete("k")
        assert sync_cache.get_json("k") is None

    def test_disabled_cache_never_connects(self):
        cache = SyncRedisCache(connect=_broken_connect, enabled=_disabled)
        assert cache.get_json("k") is None
        assert cache.set_json("k", {"v": 1}, ttl=60) is False

    # A connection error must be treated as a miss rather than raising into the
    # request that asked for it, so the caller can fall back to a slow fetch
    def test_connection_error_reads_as_a_miss(self):
        cache = SyncRedisCache(
            connect=lambda: _BrokenClient(), enabled=_enabled
        )
        assert cache.get_json("k") is None

    def test_connection_error_makes_writes_a_no_op(self):
        cache = SyncRedisCache(
            connect=lambda: _BrokenClient(), enabled=_enabled
        )
        assert cache.set_json("k", {"v": 1}, ttl=60) is False

    def test_unencodable_value_is_refused_without_raising(self, sync_cache):
        assert sync_cache.set_json("k", object(), ttl=60) is False

    def test_acquire_lock_is_exclusive(self, sync_cache):
        assert sync_cache.acquire_lock("lock", ttl=30)
        assert sync_cache.acquire_lock("lock", ttl=30) is None

    # A lock that is released can be reacquired, and the token is distinct from
    # the first one so a stale holder cannot release it.
    def test_released_lock_can_be_reacquired(self, sync_cache):
        token = sync_cache.acquire_lock("lock", ttl=30)
        sync_cache.release_lock("lock", token)
        assert sync_cache.acquire_lock("lock", ttl=30)

    def test_each_acquisition_gets_a_distinct_token(self, sync_cache):
        first = sync_cache.acquire_lock("lock", ttl=30)
        sync_cache.release_lock("lock", first)
        assert sync_cache.acquire_lock("lock", ttl=30) != first

    # A lock that is released with a stale token must not release the lock its
    # successor took, or both will rebuild the same value at once
    def test_release_with_a_stale_token_leaves_the_lock_alone(self, sync_cache):
        stale = sync_cache.acquire_lock("lock", ttl=30)
        sync_cache._get_client().delete("lock")
        successor = sync_cache.acquire_lock("lock", ttl=30)

        sync_cache.release_lock("lock", stale)

        assert sync_cache.acquire_lock("lock", ttl=30) is None
        assert successor is not None

    def test_release_without_a_token_is_a_no_op(self, sync_cache):
        sync_cache.acquire_lock("lock", ttl=30)
        sync_cache.release_lock("lock", None)
        assert sync_cache.acquire_lock("lock", ttl=30) is None


class TestAsyncCache:
    async def test_set_then_get_round_trips(self, async_cache):
        await async_cache.set_json("k", {"v": "x"}, ttl=60)
        assert await async_cache.get_json("k") == {"v": "x"}

    async def test_miss_returns_none(self, async_cache):
        assert await async_cache.get_json("nope") is None

    async def test_get_many_returns_only_present_keys(self, async_cache):
        await async_cache.set_json("a", {"v": 1}, ttl=60)
        result = await async_cache.get_many_json(["a", "b"])
        assert result == {"a": {"v": 1}}

    async def test_get_many_with_no_keys_returns_empty(self, async_cache):
        assert await async_cache.get_many_json([]) == {}

    async def test_set_many_writes_every_entry(self, async_cache):
        await async_cache.set_many_json(
            {"a": ({"v": 1}, 60), "b": ({"v": 2}, 60)}
        )
        assert await async_cache.get_many_json(["a", "b"]) == {
            "a": {"v": 1},
            "b": {"v": 2},
        }

    async def test_set_many_honours_per_entry_ttls(self, async_cache):
        await async_cache.set_many_json(
            {"short": ({"v": 1}, 10), "long": ({"v": 2}, 900)}
        )
        client = async_cache._get_client()
        assert await client.ttl("short") <= 10
        assert await client.ttl("long") > 10

    async def test_disabled_cache_never_connects(self):
        cache = AsyncRedisCache(connect=_broken_connect, enabled=_disabled)
        assert await cache.get_json("k") is None
        assert await cache.set_json("k", {"v": 1}, ttl=60) is False

    async def test_connection_error_reads_as_a_miss(self):
        cache = AsyncRedisCache(
            connect=lambda: _BrokenClient(), enabled=_enabled
        )
        assert await cache.get_json("k") is None

    async def test_eval_script_returns_none_when_unavailable(self):
        cache = AsyncRedisCache(connect=_broken_connect, enabled=_disabled)
        assert await cache.eval_script("return 1", ["k"], []) is None

    async def test_client_is_reused_within_one_loop(self, async_cache):
        assert async_cache._get_client() is async_cache._get_client()

    def test_each_event_loop_gets_its_own_client(self, async_cache):
        clients = []

        async def capture():
            clients.append(async_cache._get_client())

        for _ in range(2):
            asyncio.run(capture())

        assert clients[0] is not clients[1]

    def test_concurrent_loops_do_not_evict_each_others_clients(
        self, async_cache
    ):
        built = []
        original_connect = async_cache._connect

        def counting_connect():
            client = original_connect()
            built.append(client)
            return client

        async_cache._connect = counting_connect
        barrier = threading.Barrier(4)

        async def five_operations():
            barrier.wait()
            for index in range(5):
                await async_cache.set_json(f"k{index}", {"v": index}, ttl=60)

        threads = [
            threading.Thread(target=lambda: asyncio.run(five_operations()))
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(built) == 4

    def test_clients_of_closed_loops_are_dropped(self, async_cache):
        asyncio.run(_touch_cache(async_cache))
        asyncio.run(_touch_cache(async_cache))
        assert len(async_cache._clients) <= 1

    async def test_aclose_releases_the_running_loops_client(self, async_cache):
        await async_cache.set_json("k", {"v": 1}, ttl=60)
        await async_cache.aclose()
        assert async_cache._clients == {}

    async def test_acquire_lock_is_exclusive(self, async_cache):
        assert await async_cache.acquire_lock("lock", ttl=30)
        assert await async_cache.acquire_lock("lock", ttl=30) is None

    # A lock that is released can be reacquired, and the token is distinct from
    # the first one so a stale holder cannot release it.
    async def test_released_lock_can_be_reacquired(self, async_cache):
        token = await async_cache.acquire_lock("lock", ttl=30)
        await async_cache.release_lock("lock", token)
        assert await async_cache.acquire_lock("lock", ttl=30)

    async def test_each_acquisition_gets_a_distinct_token(self, async_cache):
        first = await async_cache.acquire_lock("lock", ttl=30)
        await async_cache.release_lock("lock", first)
        assert await async_cache.acquire_lock("lock", ttl=30) != first

    # A lock that is released with a stale token must not release the lock its
    # successor took, or both will rebuild the same value at once
    async def test_release_with_a_stale_token_leaves_the_lock_alone(
        self, async_cache
    ):
        stale = await async_cache.acquire_lock("lock", ttl=30)
        await async_cache._get_client().delete("lock")
        successor = await async_cache.acquire_lock("lock", ttl=30)

        await async_cache.release_lock("lock", stale)

        assert await async_cache.acquire_lock("lock", ttl=30) is None
        assert successor is not None

    async def test_release_without_a_token_is_a_no_op(self, async_cache):
        await async_cache.acquire_lock("lock", ttl=30)
        await async_cache.release_lock("lock", None)
        assert await async_cache.acquire_lock("lock", ttl=30) is None

    async def test_acquire_lock_returns_none_when_disabled(self):
        cache = AsyncRedisCache(connect=_broken_connect, enabled=_disabled)
        assert await cache.acquire_lock("lock", ttl=30) is None


class TestCircuitBreaker:
    def test_starts_closed(self):
        assert CircuitBreaker("t").allows_request() is True

    def test_opens_after_a_failure(self):
        breaker = CircuitBreaker("t", retry_after_s=60)
        breaker.record_failure(RedisConnectionError("down"))
        assert breaker.allows_request() is False

    def test_allows_a_probe_once_the_retry_window_elapses(self):
        breaker = CircuitBreaker("t", retry_after_s=0)
        breaker.record_failure(RedisConnectionError("down"))
        assert breaker.allows_request() is True

    def test_only_one_caller_probes_per_retry_window(self):
        breaker = CircuitBreaker("t", retry_after_s=0.5)
        breaker.record_failure(RedisConnectionError("down"))
        breaker._open_until = time.monotonic()  # window has just elapsed

        allowed = [breaker.allows_request() for _ in range(20)]
        assert allowed.count(True) == 1

    def test_a_concurrent_batch_still_yields_one_probe(self):
        breaker = CircuitBreaker("t", retry_after_s=0.5)
        breaker.record_failure(RedisConnectionError("down"))
        breaker._open_until = time.monotonic()

        results = []
        barrier = threading.Barrier(8)

        def probe():
            barrier.wait()
            results.append(breaker.allows_request())

        threads = [threading.Thread(target=probe) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results.count(True) == 1

    def test_checking_availability_does_not_spend_the_probe(self):
        breaker = CircuitBreaker("t", retry_after_s=0.5)
        breaker.record_failure(RedisConnectionError("down"))
        breaker._open_until = time.monotonic()

        assert breaker.is_available is True
        assert breaker.is_available is True
        assert breaker.allows_request() is True

    def test_availability_is_false_while_the_window_is_open(self):
        breaker = CircuitBreaker("t", retry_after_s=60)
        breaker.record_failure(RedisConnectionError("down"))
        assert breaker.is_available is False

    def test_success_closes_it_again(self):
        breaker = CircuitBreaker("t", retry_after_s=60)
        breaker.record_failure(RedisConnectionError("down"))
        breaker.record_success()
        assert breaker.allows_request() is True

    # A single request can query the cache hundreds of times - one outage must
    # not produce hundreds of identical warnings in the log
    def test_repeated_failures_warn_only_on_the_transition(self, caplog):
        breaker = CircuitBreaker("t", retry_after_s=60)
        with caplog.at_level("WARNING"):
            for _ in range(50):
                breaker.record_failure(RedisConnectionError("down"))
        assert len(caplog.records) == 1

    def test_recovery_is_logged(self, caplog):
        breaker = CircuitBreaker("t", retry_after_s=0)
        breaker.record_failure(RedisConnectionError("down"))
        with caplog.at_level("WARNING"):
            breaker.record_success()
        assert any("recovered" in r.message for r in caplog.records)


class TestBoundedTTLCache:
    def test_set_then_get_round_trips(self):
        cache = BoundedTTLCache()
        cache.set("k", "v", ttl=60)
        assert cache.get("k") == "v"

    def test_missing_key_returns_none(self):
        assert BoundedTTLCache().get("nope") is None

    def test_expired_entry_returns_none(self):
        cache = BoundedTTLCache()
        cache.set("k", "v", ttl=0)
        time.sleep(0.01)
        assert cache.get("k") is None

    # This replaced an unbounded dict that never evicted anything, so the bound
    # is the reason the class exists
    def test_evicts_least_recently_used_past_the_limit(self):
        cache = BoundedTTLCache(max_entries=2)
        cache.set("a", 1, ttl=60)
        cache.set("b", 2, ttl=60)
        cache.set("c", 3, ttl=60)
        assert len(cache) == 2
        assert cache.get("a") is None

    def test_reading_an_entry_protects_it_from_eviction(self):
        cache = BoundedTTLCache(max_entries=2)
        cache.set("a", 1, ttl=60)
        cache.set("b", 2, ttl=60)
        cache.get("a")
        cache.set("c", 3, ttl=60)
        assert cache.get("a") == 1
        assert cache.get("b") is None

    def test_delete_removes_the_entry(self):
        cache = BoundedTTLCache()
        cache.set("k", "v", ttl=60)
        cache.delete("k")
        assert cache.get("k") is None

    def test_rejects_a_non_positive_limit(self):
        with pytest.raises(ValueError):
            BoundedTTLCache(max_entries=0)


class TestFallbackCache:
    def test_uses_redis_when_healthy(self, sync_cache):
        cache = FallbackCache(sync_cache)
        cache.set_json("k", {"v": 1}, ttl=60)
        assert sync_cache.get_json("k") == {"v": 1}

    def test_falls_back_to_local_when_redis_is_disabled(self):
        primary = SyncRedisCache(connect=_broken_connect, enabled=_disabled)
        cache = FallbackCache(primary)
        cache.set_json("k", {"v": 1}, ttl=60)
        assert cache.get_json("k") == {"v": 1}

    def test_delete_works_on_the_local_tier(self):
        cache = FallbackCache(
            SyncRedisCache(connect=_broken_connect, enabled=_disabled)
        )
        cache.set_json("k", {"v": 1}, ttl=60)
        cache.delete("k")
        assert cache.get_json("k") is None

    # Without Redis there is nothing to coordinate between processes so the
    # caller must be told to go ahead rather than being blocked forever
    def test_refresh_slot_is_granted_when_redis_is_unavailable(self):
        cache = FallbackCache(
            SyncRedisCache(connect=_broken_connect, enabled=_disabled)
        )
        assert cache.acquire_refresh_slot("lock", ttl=30)
        assert cache.acquire_refresh_slot("lock", ttl=30)

    def test_refresh_slot_is_exclusive_when_redis_is_available(
        self, sync_cache
    ):
        cache = FallbackCache(sync_cache)
        assert cache.acquire_refresh_slot("lock", ttl=30)
        assert cache.acquire_refresh_slot("lock", ttl=30) is None

    def test_released_refresh_slot_can_be_retaken(self, sync_cache):
        cache = FallbackCache(sync_cache)
        token = cache.acquire_refresh_slot("lock", ttl=30)
        cache.release_refresh_slot("lock", token)
        assert cache.acquire_refresh_slot("lock", ttl=30)

    def test_stale_holder_cannot_release_the_successors_slot(self, sync_cache):
        cache = FallbackCache(sync_cache)
        stale = cache.acquire_refresh_slot("lock", ttl=30)
        sync_cache._get_client().delete("lock")
        cache.acquire_refresh_slot("lock", ttl=30)

        cache.release_refresh_slot("lock", stale)

        assert cache.acquire_refresh_slot("lock", ttl=30) is None

    def test_a_failed_primary_read_falls_through_to_local(self):
        primary = _FlakyCache(fail=True)
        cache = FallbackCache(primary)
        cache.set_json("k", {"v": 1}, ttl=60)

        primary.heal()
        assert cache.get_json("k") == {"v": 1}

    def test_a_failed_primary_write_is_kept_locally(self):
        primary = _FlakyCache(fail=True)
        cache = FallbackCache(primary)

        assert cache.set_json("k", {"v": 1}, ttl=60) is True

        primary.fail = False
        assert cache.get_json("k") == {"v": 1}

    def test_a_healthy_primary_miss_stays_a_miss(self, sync_cache):
        cache = FallbackCache(sync_cache)
        assert cache.get_json("never-written") is None

    def test_delete_clears_both_tiers(self):
        primary = _FlakyCache(fail=True)
        cache = FallbackCache(primary)
        cache.set_json("k", {"v": 1}, ttl=60)

        primary.fail = False
        primary.set_json("k", {"v": 2}, ttl=60)
        cache.delete("k")

        assert cache.get_json("k") is None
        primary.fail = True
        assert cache.get_json("k") is None


# Async counterpart of _FlakyCache, for AsyncFallbackCache's fallback tests
class _AsyncFlakyCache:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self._tripped = False
        self._entries: dict[str, object] = {}

    @property
    def is_healthy(self) -> bool:
        return not self._tripped

    def heal(self) -> None:
        self._tripped = False

    def _record(self, failed: bool) -> bool:
        self._tripped = failed
        return not failed

    async def get_json(self, key: str):
        if not self._record(self.fail):
            return None
        return self._entries.get(key)

    async def set_json(self, key: str, value: object, ttl: int) -> bool:
        if not self._record(self.fail):
            return False
        self._entries[key] = value
        return True

    async def delete(self, key: str) -> bool:
        if not self._record(self.fail):
            return False
        self._entries.pop(key, None)
        return True


class TestAsyncFallbackCache:
    async def test_uses_redis_when_healthy(self, async_cache):
        cache = AsyncFallbackCache(async_cache)
        await cache.set_json("k", {"v": 1}, ttl=60)
        assert await async_cache.get_json("k") == {"v": 1}

    async def test_falls_back_to_local_when_redis_is_disabled(self):
        primary = AsyncRedisCache(connect=_broken_connect, enabled=_disabled)
        cache = AsyncFallbackCache(primary)
        await cache.set_json("k", {"v": 1}, ttl=60)
        assert await cache.get_json("k") == {"v": 1}

    async def test_delete_works_on_the_local_tier(self):
        cache = AsyncFallbackCache(
            AsyncRedisCache(connect=_broken_connect, enabled=_disabled)
        )
        await cache.set_json("k", {"v": 1}, ttl=60)
        await cache.delete("k")
        assert await cache.get_json("k") is None

    # Without Redis there is nothing to coordinate between processes so the
    # caller must be told to go ahead rather than being blocked forever
    async def test_refresh_slot_is_granted_when_redis_is_unavailable(self):
        cache = AsyncFallbackCache(
            AsyncRedisCache(connect=_broken_connect, enabled=_disabled)
        )
        assert await cache.acquire_refresh_slot("lock", ttl=30)
        assert await cache.acquire_refresh_slot("lock", ttl=30)

    async def test_refresh_slot_is_exclusive_when_redis_is_available(
        self, async_cache
    ):
        cache = AsyncFallbackCache(async_cache)
        assert await cache.acquire_refresh_slot("lock", ttl=30)
        assert await cache.acquire_refresh_slot("lock", ttl=30) is None

    async def test_released_refresh_slot_can_be_retaken(self, async_cache):
        cache = AsyncFallbackCache(async_cache)
        token = await cache.acquire_refresh_slot("lock", ttl=30)
        await cache.release_refresh_slot("lock", token)
        assert await cache.acquire_refresh_slot("lock", ttl=30)

    async def test_stale_holder_cannot_release_the_successors_slot(
        self, async_cache
    ):
        cache = AsyncFallbackCache(async_cache)
        stale = await cache.acquire_refresh_slot("lock", ttl=30)
        await async_cache._get_client().delete("lock")
        await cache.acquire_refresh_slot("lock", ttl=30)

        await cache.release_refresh_slot("lock", stale)

        assert await cache.acquire_refresh_slot("lock", ttl=30) is None

    async def test_a_failed_primary_read_falls_through_to_local(self):
        primary = _AsyncFlakyCache(fail=True)
        cache = AsyncFallbackCache(primary)
        await cache.set_json("k", {"v": 1}, ttl=60)

        primary.heal()
        assert await cache.get_json("k") == {"v": 1}

    async def test_a_failed_primary_write_is_kept_locally(self):
        primary = _AsyncFlakyCache(fail=True)
        cache = AsyncFallbackCache(primary)

        assert await cache.set_json("k", {"v": 1}, ttl=60) is True

        primary.fail = False
        assert await cache.get_json("k") == {"v": 1}

    async def test_a_healthy_primary_miss_stays_a_miss(self, async_cache):
        cache = AsyncFallbackCache(async_cache)
        assert await cache.get_json("never-written") is None

    async def test_delete_clears_both_tiers(self):
        primary = _AsyncFlakyCache(fail=True)
        cache = AsyncFallbackCache(primary)
        await cache.set_json("k", {"v": 1}, ttl=60)

        primary.fail = False
        await primary.set_json("k", {"v": 2}, ttl=60)
        await cache.delete("k")

        assert await cache.get_json("k") is None
        primary.fail = True
        assert await cache.get_json("k") is None


# Wraps FallbackCache so parity tests can await it exactly like
# AsyncFallbackCache letting both run through one shared test body
class _SyncFallbackAdapter:
    def __init__(self, primary):
        self._cache = FallbackCache(primary)

    async def get_json(self, key):
        return self._cache.get_json(key)

    async def set_json(self, key, value, ttl):
        return self._cache.set_json(key, value, ttl)

    async def delete(self, key):
        return self._cache.delete(key)


class _AsyncFallbackAdapter:
    def __init__(self, primary):
        self._cache = AsyncFallbackCache(primary)

    async def get_json(self, key):
        return await self._cache.get_json(key)

    async def set_json(self, key, value, ttl):
        return await self._cache.set_json(key, value, ttl)

    async def delete(self, key):
        return await self._cache.delete(key)


# Runs identical scenarios against both hand-synced implementations through a
# common async interface, catching the two implementations silently diverging
@pytest.mark.parametrize(
    "adapter_cls, flaky_cls",
    [
        (_SyncFallbackAdapter, _FlakyCache),
        (_AsyncFallbackAdapter, _AsyncFlakyCache),
    ],
    ids=["sync", "async"],
)
class TestFallbackParity:
    async def test_healthy_primary_round_trips(self, adapter_cls, flaky_cls):
        cache = adapter_cls(flaky_cls(fail=False))
        await cache.set_json("k", {"v": 1}, ttl=60)
        assert await cache.get_json("k") == {"v": 1}

    async def test_failed_primary_read_falls_through_to_local(
        self, adapter_cls, flaky_cls
    ):
        primary = flaky_cls(fail=True)
        cache = adapter_cls(primary)
        await cache.set_json("k", {"v": 1}, ttl=60)

        primary.heal()
        assert await cache.get_json("k") == {"v": 1}

    async def test_failed_primary_write_is_kept_locally(
        self, adapter_cls, flaky_cls
    ):
        primary = flaky_cls(fail=True)
        cache = adapter_cls(primary)
        assert await cache.set_json("k", {"v": 1}, ttl=60) is True

        primary.fail = False
        assert await cache.get_json("k") == {"v": 1}

    async def test_delete_clears_both_tiers(self, adapter_cls, flaky_cls):
        primary = flaky_cls(fail=True)
        cache = adapter_cls(primary)
        await cache.set_json("k", {"v": 1}, ttl=60)

        primary.fail = False
        # Lands in the primary tier since it is healthy again
        await cache.set_json("k", {"v": 2}, ttl=60)
        await cache.delete("k")

        assert await cache.get_json("k") is None
        primary.fail = True
        assert await cache.get_json("k") is None

    async def test_a_healthy_primary_miss_stays_a_miss(
        self, adapter_cls, flaky_cls
    ):
        cache = adapter_cls(flaky_cls(fail=False))
        assert await cache.get_json("never-written") is None


# Checked against the real Sync/AsyncRedisCache primaries rather than the
# Flaky doubles above since only the real ones implement acquire_lock
class TestFallbackRefreshSlotParity:
    async def test_granted_when_primary_unavailable_sync(self):
        cache = FallbackCache(
            SyncRedisCache(connect=_broken_connect, enabled=_disabled)
        )
        assert cache.acquire_refresh_slot("lock", ttl=30)
        assert cache.acquire_refresh_slot("lock", ttl=30)

    async def test_granted_when_primary_unavailable_async(self):
        cache = AsyncFallbackCache(
            AsyncRedisCache(connect=_broken_connect, enabled=_disabled)
        )
        assert await cache.acquire_refresh_slot("lock", ttl=30)
        assert await cache.acquire_refresh_slot("lock", ttl=30)
