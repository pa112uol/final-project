"""FastAPI dependencies: settings, the shared pipeline client namespace, and
a concurrency cap on simultaneous pipeline runs.
"""

import asyncio

from recommendations.index import Clients, build_clients

from .config import Settings, get_settings

# Caps simultaneous recommendations pipeline runs. Each run fans out ~150
# upstream HTTP calls; without a cap, a burst of concurrent requests queues
# behind the httpx connection pools and the MusicBrainz rate limiter and
# produces worse tail latency than the old thread-per-request model
MAX_CONCURRENT_PIPELINE_RUNS = 20

_pipeline_clients: Clients | None = None
_pipeline_semaphore: asyncio.Semaphore | None = None


# Built once in the app lifespan and reused for every request. Falls back to
# a lazy build when the lifespan has not run
async def get_pipeline_clients() -> Clients:
    global _pipeline_clients
    # async avoids the worker-thread race a sync dependency would hit here
    if _pipeline_clients is None:
        _pipeline_clients = build_clients()
    return _pipeline_clients


def set_pipeline_clients(clients: Clients | None) -> None:
    global _pipeline_clients
    _pipeline_clients = clients


# Same eager-in-lifespan, lazy-fallback, async pattern as get_pipeline_clients
async def get_pipeline_semaphore() -> asyncio.Semaphore:
    global _pipeline_semaphore
    if _pipeline_semaphore is None:
        _pipeline_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PIPELINE_RUNS)
    return _pipeline_semaphore


def set_pipeline_semaphore(semaphore: asyncio.Semaphore | None) -> None:
    global _pipeline_semaphore
    _pipeline_semaphore = semaphore


# Builds the shared clients namespace. Split out from the lifespan so tests
# can call it directly without spinning up the app
def init_pipeline_clients() -> Clients:
    clients = build_clients()
    set_pipeline_clients(clients)
    return clients


# Builds the pipeline semaphore, mirroring init_pipeline_clients
def init_pipeline_semaphore() -> asyncio.Semaphore:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PIPELINE_RUNS)
    set_pipeline_semaphore(semaphore)
    return semaphore


# Async wrapper so FastAPI awaits get_settings on the event loop instead of
# a worker thread; get_settings itself stays sync for non-request callers
async def get_settings_dependency() -> Settings:
    return get_settings()


__all__ = [
    "Settings",
    "get_settings",
    "get_settings_dependency",
    "get_pipeline_clients",
    "set_pipeline_clients",
    "get_pipeline_semaphore",
    "set_pipeline_semaphore",
    "init_pipeline_clients",
    "init_pipeline_semaphore",
]
