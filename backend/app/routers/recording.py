import logging

from fastapi import APIRouter, Depends, Query, Response

from app.deps import get_pipeline_clients
from recommendations.types import resolved_to_dict

logger = logging.getLogger(__name__)
router = APIRouter()


# Lazily resolves one track's MusicBrainz recording data (duration, album,
# release date). Caching/TTL is handled by the cached client it calls
@router.get("/recording/")
async def recording(
    response: Response,
    title: str = Query(default=""),
    mbid: str = Query(default=""),
    artist: str = Query(default=""),
    clients=Depends(get_pipeline_clients),
) -> dict:
    title = title.strip()
    if not title:
        response.status_code = 400
        return {"error": "title required"}

    mbid = mbid.strip()
    artist = artist.strip()

    from clients.musicbrainz import EMPTY_RECORDING
    from recommendations import index

    try:
        resolved = await index.resolve_recording(
            mbid, title, artist, clients=clients
        )
    except Exception:
        logger.error(
            "[recording] resolution failed for %r by %r",
            title,
            artist,
            exc_info=True,
        )
        resolved = {"mbid": mbid, **EMPTY_RECORDING}

    return resolved_to_dict(resolved)
