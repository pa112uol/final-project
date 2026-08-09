import asyncio

import pytest

from app import deps
from app.config import Settings


# Ensures a lazily built clients/semaphore singleton never leaks into the
# next test mirroring how the app lifespan resets state on shutdown
@pytest.fixture(autouse=True)
def reset_pipeline_state():
    yield
    deps.set_pipeline_clients(None)
    deps.set_pipeline_semaphore(None)


class TestGetPipelineClients:
    async def test_lazily_builds_when_not_initialized(self):
        deps.set_pipeline_clients(None)
        clients = await deps.get_pipeline_clients()
        assert callable(clients.fetch_track_tags)
        assert callable(clients.resolve_recording_mbid)

    async def test_returns_the_same_instance_on_repeated_calls(self):
        deps.set_pipeline_clients(None)
        first = await deps.get_pipeline_clients()
        second = await deps.get_pipeline_clients()
        assert first is second

    async def test_returns_the_instance_set_by_init(self):
        clients = deps.init_pipeline_clients()
        assert await deps.get_pipeline_clients() is clients


class TestGetPipelineSemaphore:
    async def test_lazily_builds_when_not_initialized(self):
        deps.set_pipeline_semaphore(None)
        semaphore = await deps.get_pipeline_semaphore()
        assert isinstance(semaphore, asyncio.Semaphore)

    async def test_returns_the_same_instance_on_repeated_calls(self):
        deps.set_pipeline_semaphore(None)
        first = await deps.get_pipeline_semaphore()
        second = await deps.get_pipeline_semaphore()
        assert first is second

    # A burst of concurrent dependency resolutions must not build more than
    # one semaphore or the effective concurrency cap silently rises
    async def test_concurrent_lazy_builds_yield_a_single_semaphore(self):
        deps.set_pipeline_semaphore(None)
        results = await asyncio.gather(
            *[deps.get_pipeline_semaphore() for _ in range(50)]
        )
        assert len({id(s) for s in results}) == 1

    async def test_init_builds_a_semaphore_capped_at_the_configured_limit(self):
        semaphore = deps.init_pipeline_semaphore()
        assert semaphore._value == deps.MAX_CONCURRENT_PIPELINE_RUNS


class TestGetSettingsDependency:
    async def test_returns_a_settings_instance(self):
        result = await deps.get_settings_dependency()
        assert isinstance(result, Settings)

    async def test_matches_the_sync_config_loader(self):
        assert await deps.get_settings_dependency() is deps.get_settings()
