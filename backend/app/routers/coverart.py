from fastapi import APIRouter, Query, Response

from caching.config import NEGATIVE_TTL_S, TTL_COVERART
from caching.keys import build_key
from caching.local import get_async_view_cache

router = APIRouter()

COVERART_NAMESPACE = "coverart"
# A "no cover art" result is often a transient failure (rate limit, timeout)
# rather than a real fact about the recording, so it's only cached briefly.
# A found url is cached for a long time since that data doesn't change.
COVERART_NEGATIVE_TTL_S = NEGATIVE_TTL_S

# The url is stored inside an envelope so a cached "no cover art" can be told
# apart from a cache miss
_COVERART_URL_FIELD = "url"


@router.get("/coverart/")
async def coverart(
    response: Response,
    mbid: str = Query(default=""),
    releaseMbid: str = Query(default=""),
) -> dict:
    mbid = mbid.strip()
    if not mbid:
        response.status_code = 400
        return {"error": "mbid required"}

    # Optional release the caller already resolved, so fetch_cover_art_url can skip its own lookup.
    release_mbid = releaseMbid.strip() or None

    cache = get_async_view_cache()
    key = build_key(COVERART_NAMESPACE, mbid)
    cached = await cache.get_json(key)
    if isinstance(cached, dict) and _COVERART_URL_FIELD in cached:
        return _coverart_body(response, cached[_COVERART_URL_FIELD])

    from clients.coverart import fetch_cover_art_url

    url = await fetch_cover_art_url(mbid, release_mbid)
    await cache.set_json(
        key,
        {_COVERART_URL_FIELD: url},
        TTL_COVERART if url else COVERART_NEGATIVE_TTL_S,
    )
    return _coverart_body(response, url)


# A missing url is a 404 rather than an empty 200, which is what the frontend's
# CoverArt component distinguishes on
def _coverart_body(response: Response, url: str | None) -> dict:
    if not url:
        response.status_code = 404
        return {"error": "No cover art found"}
    return {"url": url}
