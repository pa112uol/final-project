import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.deps import (
    init_pipeline_clients,
    init_pipeline_semaphore,
    set_pipeline_clients,
    set_pipeline_semaphore,
)
from app.routers import coverart, random_tracks, recommendations, recording, search
from caching.async_cache import get_async_cache
from clients.http import close_clients

logger = logging.getLogger(__name__)


# Builds the pipeline clients and semaphore once at startup, and tears down
# the pooled httpx clients and the Redis connection pool on shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pipeline_clients()
    init_pipeline_semaphore()
    try:
        yield
    finally:
        set_pipeline_clients(None)
        set_pipeline_semaphore(None)
        await close_clients()
        await get_async_cache().aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    # No custom response class: FastAPI's built-in JSON serialization is
    # already the fast path, so a wrapper class like ORJSONResponse only
    # adds overhead here
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(recommendations.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(recording.router, prefix="/api")
    app.include_router(random_tracks.router, prefix="/api")
    app.include_router(coverart.router, prefix="/api")

    return app


app = create_app()
