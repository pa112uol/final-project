import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caching.async_cache import AsyncRedisCache
from caching.ratelimit import MB_SLOT_KEY, RedisRateLimiter
from clients import musicbrainz
from clients.musicbrainz import MB_MIN_INTERVAL_S

INTERVAL_S = 1.05


@pytest.fixture
def limiter(async_cache_enabled):
    return RedisRateLimiter(MB_SLOT_KEY, INTERVAL_S, cache=async_cache_enabled)


class TestReserve:
    async def test_first_reservation_does_not_wait(self, limiter):
        assert await limiter.reserve() == 0.0

    async def test_successive_reservations_are_spaced_by_the_interval(
        self, limiter
    ):
        waits = [await limiter.reserve() for _ in range(4)]

        assert waits[0] == 0.0
        for earlier, later in zip(waits, waits[1:]):
            assert later - earlier == pytest.approx(INTERVAL_S, abs=0.05)

    # Every caller gets its own slot even when they all arrive at once
    async def test_concurrent_callers_each_get_a_distinct_slot(self, limiter):
        waits = await asyncio.gather(*[limiter.reserve() for _ in range(5)])

        assert len(set(waits)) == 5
        ordered = sorted(waits)
        for earlier, later in zip(ordered, ordered[1:]):
            assert later - earlier == pytest.approx(INTERVAL_S, abs=0.05)

    # Two limiter instances stand in for two worker processes sharing one Redis.
    async def test_separate_instances_share_the_same_slot_sequence(
        self, async_cache_enabled
    ):
        first = RedisRateLimiter(
            MB_SLOT_KEY, INTERVAL_S, cache=async_cache_enabled
        )
        second = RedisRateLimiter(
            MB_SLOT_KEY, INTERVAL_S, cache=async_cache_enabled
        )

        assert await first.reserve() == 0.0
        assert await second.reserve() == pytest.approx(INTERVAL_S, abs=0.05)

    async def test_different_keys_do_not_contend(self, async_cache_enabled):
        first = RedisRateLimiter(
            "limiter:a", INTERVAL_S, cache=async_cache_enabled
        )
        second = RedisRateLimiter(
            "limiter:b", INTERVAL_S, cache=async_cache_enabled
        )

        assert await first.reserve() == 0.0
        assert await second.reserve() == 0.0

    # None means Redis is unavailable, so the caller falls back to local
    # limiting
    async def test_returns_none_when_the_cache_is_unavailable(self):
        disabled = AsyncRedisCache(connect=lambda: None, enabled=lambda: False)
        limiter = RedisRateLimiter(MB_SLOT_KEY, INTERVAL_S, cache=disabled)
        assert await limiter.reserve() is None

    async def test_returns_none_on_an_unexpected_script_result(
        self, monkeypatch
    ):
        cache = MagicMock()
        cache.eval_script = AsyncMock(return_value="not-a-number")
        limiter = RedisRateLimiter(MB_SLOT_KEY, INTERVAL_S, cache=cache)
        assert await limiter.reserve() is None

    @pytest.mark.parametrize("interval", [0, -1])
    def test_rejects_a_non_positive_interval(self, interval):
        with pytest.raises(ValueError):
            RedisRateLimiter(MB_SLOT_KEY, interval)


class TestMbFetchIntegration:
    def _mock_client(self, response=None):
        client = MagicMock()
        client.get = AsyncMock(
            return_value=(
                response
                if response is not None
                else MagicMock(status_code=200, is_success=True)
            )
        )
        return client

    # With Redis available mb_fetch must reserve a slot rather than fall back to
    # the in-process lock, whose spacing does not survive a new event loop
    async def test_uses_the_redis_limiter_when_available(
        self, async_cache_enabled
    ):
        sleeps = []

        async def record_sleep(seconds):
            sleeps.append(seconds)

        with patch(
            "clients.musicbrainz.get_client", return_value=self._mock_client()
        ), patch("clients.musicbrainz.asyncio.sleep", new=record_sleep), patch(
            "clients.musicbrainz._mb_get_locally_limited"
        ) as local_path:
            await musicbrainz.mb_fetch("https://example.com/a")
            await musicbrainz.mb_fetch("https://example.com/b")

        local_path.assert_not_called()
        # First call takes the free slot, the second waits an interval for its own
        assert sleeps == [pytest.approx(MB_MIN_INTERVAL_S, abs=0.05)]

    async def test_falls_back_to_the_local_lock_without_redis(self):
        client = self._mock_client()
        with patch(
            "clients.musicbrainz.get_client", return_value=client
        ), patch("clients.musicbrainz.asyncio.sleep", new=AsyncMock()):
            result = await musicbrainz.mb_fetch("https://example.com")

        assert result.status_code == 200
        assert client.get.call_count == 1

    async def test_local_fallback_is_used_when_the_reservation_fails(self):
        client = self._mock_client()
        with patch(
            "clients.musicbrainz.get_client", return_value=client
        ), patch(
            "clients.musicbrainz.asyncio.sleep", new=AsyncMock()
        ), patch.object(
            musicbrainz._mb_limiter, "reserve", new=AsyncMock(return_value=None)
        ), patch(
            "clients.musicbrainz._mb_get_locally_limited",
            new=AsyncMock(
                return_value=MagicMock(status_code=200, is_success=True)
            ),
        ) as local_path:
            await musicbrainz.mb_fetch("https://example.com")

        local_path.assert_awaited_once()

    # The slot is consumed at reservation time, so a call that fails has still
    # spent its allowance. The retry reserves a second slot rather than reusing
    # the one the timed-out attempt reserved
    async def test_failed_attempt_still_consumes_a_slot(
        self, async_cache_enabled
    ):
        import httpx

        client = MagicMock()
        client.get = AsyncMock(
            side_effect=[
                httpx.ReadTimeout("timed out"),
                MagicMock(status_code=200, is_success=True),
            ]
        )
        with patch(
            "clients.musicbrainz.get_client", return_value=client
        ), patch(
            "clients.musicbrainz.asyncio.sleep", new=AsyncMock()
        ), patch.object(
            musicbrainz._mb_limiter,
            "reserve",
            wraps=musicbrainz._mb_limiter.reserve,
        ) as reserve:
            await musicbrainz.mb_fetch("https://example.com")

        assert client.get.call_count == 2
        assert reserve.await_count == 2

        # Two slots reserved means the stored marker sits two intervals ahead
        raw = await async_cache_enabled._get_client().get(MB_SLOT_KEY)
        assert raw is not None


class TestFailoverSpacing:
    def _mock_client(self):
        client = MagicMock()
        client.get = AsyncMock(
            return_value=MagicMock(status_code=200, is_success=True)
        )
        return client

    @pytest.fixture(autouse=True)
    def reset_local_clock(self):
        original = musicbrainz._last_request_time
        musicbrainz._last_request_time = 0.0
        yield
        musicbrainz._last_request_time = original

    async def test_the_redis_path_stamps_the_local_clock(
        self, async_cache_enabled
    ):
        with patch(
            "clients.musicbrainz.get_client", return_value=self._mock_client()
        ), patch("clients.musicbrainz.asyncio.sleep", new=AsyncMock()):
            await musicbrainz.mb_fetch("https://example.com")

        assert musicbrainz._last_request_time > 0.0

    async def test_the_local_path_waits_after_a_redis_served_request(
        self, async_cache_enabled
    ):
        sleeps = []

        async def record_sleep(seconds):
            sleeps.append(seconds)

        with patch(
            "clients.musicbrainz.get_client", return_value=self._mock_client()
        ), patch("clients.musicbrainz.asyncio.sleep", new=record_sleep):
            await musicbrainz.mb_fetch("https://example.com/a")
            sleeps.clear()
            with patch.object(
                musicbrainz._mb_limiter,
                "reserve",
                new=AsyncMock(return_value=None),
            ):
                await musicbrainz.mb_fetch("https://example.com/b")

        assert sleeps, "the local path fired without waiting out the interval"
        assert sleeps[0] == pytest.approx(MB_MIN_INTERVAL_S, abs=0.1)
