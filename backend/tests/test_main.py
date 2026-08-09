"""Tests for the FastAPI app's startup/shutdown lifespan."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import deps
from app.main import app


# Ensures pipeline state set up by one tests lifespan run never leaks into
# the next
@pytest.fixture(autouse=True)
def reset_pipeline_state():
    yield
    deps.set_pipeline_clients(None)
    deps.set_pipeline_semaphore(None)


class TestLifespan:
    async def test_initializes_pipeline_clients_and_semaphore(self):
        async with app.router.lifespan_context(app):
            assert deps._pipeline_clients is not None
            assert deps._pipeline_semaphore is not None

    async def test_tears_down_pipeline_state_on_shutdown(self):
        async with app.router.lifespan_context(app):
            pass
        assert deps._pipeline_clients is None
        assert deps._pipeline_semaphore is None

    async def test_shutdown_closes_the_pooled_httpx_clients(self):
        with patch("app.main.close_clients", new=AsyncMock()) as mock_close:
            async with app.router.lifespan_context(app):
                pass
        mock_close.assert_awaited_once()

    # Rshutdown must close the Redis connection pool too, not
    # just the httpx clients or every restart/reload leaks connections
    async def test_shutdown_closes_the_redis_connection_pool(self):
        mock_cache = MagicMock()
        mock_cache.aclose = AsyncMock()
        with patch("app.main.get_async_cache", return_value=mock_cache):
            async with app.router.lifespan_context(app):
                pass
        mock_cache.aclose.assert_awaited_once()
