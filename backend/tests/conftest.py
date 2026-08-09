import fakeredis
import httpx
import pytest

from caching.async_cache import AsyncRedisCache, set_async_cache
from caching.local import (
    AsyncFallbackCache,
    FallbackCache,
    set_async_view_cache,
    set_view_cache,
)
from caching.sync_cache import SyncRedisCache, set_sync_cache


def _disabled():
    return False


def _enabled():
    return True


# Points every cache facade at a disabled instance and restores the defaults
# afterwards
@pytest.fixture(autouse=True)
def cache_disabled():
    set_sync_cache(SyncRedisCache(connect=_unreachable, enabled=_disabled))
    set_async_cache(AsyncRedisCache(connect=_unreachable, enabled=_disabled))
    set_view_cache(
        FallbackCache(SyncRedisCache(connect=_unreachable, enabled=_disabled))
    )
    set_async_view_cache(
        AsyncFallbackCache(
            AsyncRedisCache(connect=_unreachable, enabled=_disabled)
        )
    )
    yield
    set_sync_cache(None)
    set_async_cache(None)
    set_view_cache(None)
    set_async_view_cache(None)


# A disabled cache must never open a connection, so the factory raises rather
# than returning a stub
def _unreachable():
    raise AssertionError("disabled cache must not connect to Redis")


@pytest.fixture
def fake_redis():
    server = fakeredis.FakeServer()
    yield server


# Swaps the sync and view caches onto fakeredis
@pytest.fixture
def sync_cache_enabled(fake_redis):
    def connect():
        return fakeredis.FakeRedis(server=fake_redis, decode_responses=True)

    cache = SyncRedisCache(connect=connect, enabled=_enabled)
    view_cache = FallbackCache(cache)
    set_sync_cache(cache)
    set_view_cache(view_cache)
    yield view_cache
    set_sync_cache(None)
    set_view_cache(None)


# Async counterpart, for the pipeline client wrapper and the rate limiter
@pytest.fixture
def async_cache_enabled(fake_redis):
    def connect():
        return fakeredis.FakeAsyncRedis(
            server=fake_redis, decode_responses=True
        )

    cache = AsyncRedisCache(connect=connect, enabled=_enabled)
    set_async_cache(cache)
    yield cache
    set_async_cache(None)


# Swaps the async view cache onto fakeredis, for the async router tests
@pytest.fixture
def async_view_cache_enabled(fake_redis):
    def connect():
        return fakeredis.FakeAsyncRedis(
            server=fake_redis, decode_responses=True
        )

    cache = AsyncRedisCache(connect=connect, enabled=_enabled)
    view_cache = AsyncFallbackCache(cache)
    set_async_view_cache(view_cache)
    yield view_cache
    set_async_view_cache(None)


# httpx client wired directly to the FastAPI app over ASGI, replacing
# Django's RequestFactory + direct view calls
@pytest.fixture
async def api_client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    # ASGITransport does not run the lifespan on its own so it is driven here
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client
