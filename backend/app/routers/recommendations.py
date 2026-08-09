import asyncio
import logging
import random
import time

from fastapi import APIRouter, Depends, Query, Response

from app.config import Settings
from app.deps import (
    get_pipeline_clients,
    get_pipeline_semaphore,
    get_settings_dependency,
)
from recommendations.tags import MOOD_TAGS

logger = logging.getLogger(__name__)
router = APIRouter()

# Upper bound on how long one request may wait on the pipeline before giving
# up. Replaces the old unbounded _run_async(...).result() call
PIPELINE_TIMEOUT_S = 30

_REQ_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_REQ_ID_LENGTH = 5


def _clamp_novelty(raw: str) -> float:
    try:
        novelty = float(raw)
    except (ValueError, TypeError):
        novelty = 0.0
    return max(0.0, min(1.0, novelty))


@router.get("/recommendations/")
async def recommendations(
    response: Response,
    mbid: list[str] = Query(default=[]),
    title: list[str] = Query(default=[]),
    artist: list[str] = Query(default=[]),
    mood: str | None = Query(default=None),
    novelty: str = Query(default="0"),
    settings: Settings = Depends(get_settings_dependency),
    clients=Depends(get_pipeline_clients),
    semaphore: asyncio.Semaphore = Depends(get_pipeline_semaphore),
) -> dict:
    start_ms = int(time.time() * 1000)
    req_id = "".join(random.choices(_REQ_ID_ALPHABET, k=_REQ_ID_LENGTH))

    def log(phase, data):
        logger.info(
            "[REC:%s %s +%dms] %s",
            phase,
            req_id,
            int(time.time() * 1000) - start_ms,
            data,
        )

    if not settings.lastfm_api_key:
        response.status_code = 500
        return {"error": "LASTFM_API_KEY not set"}

    if not mbid:
        response.status_code = 400
        return {"error": "No seed tracks provided"}

    mood_normalized = (mood or "").lower().strip() or None
    if mood_normalized and mood_normalized not in MOOD_TAGS:
        response.status_code = 400
        return {
            "error": f"Unknown mood. Valid values: {', '.join(MOOD_TAGS.keys())}"
        }

    novelty_value = _clamp_novelty(novelty)

    seeds = [
        {
            "mbid": m,
            "title": (title[i] if i < len(title) else "").lower().strip(),
            "artist": (artist[i] if i < len(artist) else "").lower().strip(),
        }
        for i, m in enumerate(mbid)
    ]
    if len(seeds) > settings.max_seed_tracks:
        log("input", {"seedsDropped": len(seeds) - settings.max_seed_tracks})
        seeds = seeds[: settings.max_seed_tracks]

    log(
        "input",
        {"seeds": seeds, "mood": mood_normalized, "novelty": novelty_value},
    )

    # Imported lazily so tests can patch recommendations.index.get_recommendations
    # and have this call pick up the replacement
    from recommendations import index

    try:
        async with asyncio.timeout(PIPELINE_TIMEOUT_S):
            async with semaphore:
                tracks = await index.get_recommendations(
                    seeds,
                    settings.lastfm_api_key,
                    mood_normalized,
                    novelty_value,
                    clients=clients,
                )
    except TimeoutError:
        logger.error(
            "[REC] pipeline timed out after %ss", PIPELINE_TIMEOUT_S
        )
        response.status_code = 504
        return {"error": "Recommendation request timed out"}
    except Exception as err:
        logger.error("[REC] pipeline error: %s", err, exc_info=True)
        response.status_code = 500
        return {"error": "Failed to fetch recommendations"}

    log(
        "result",
        {
            "tracksReturned": len(tracks),
            "totalMs": int(time.time() * 1000) - start_ms,
        },
    )

    return {"tracks": [t.to_dict() for t in tracks]}
