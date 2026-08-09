import asyncio
import logging
import random

from fastapi import APIRouter, Response

from caching.config import (
    RANDOM_POOL_LOCK_TTL_S,
    TTL_RANDOM_POOL,
    TTL_RANDOM_POOL_STALE,
)
from caching.keys import build_key
from caching.local import AsyncFallbackCache, get_async_view_cache

logger = logging.getLogger(__name__)
router = APIRouter()

RANDOM_MB_BASE = "https://musicbrainz.org/ws/2"
RANDOM_RESPONSE_LIMIT = 5
RANDOM_CACHE_TTL_S = TTL_RANDOM_POOL

RANDOM_POOL_KEY = build_key("random", "pool")
# When a refresh fails there is nothing left under RANDOM_POOL_KEY to fall back on,
# so this preserves the old behaviour where the stale Python list stayed usable
# past its expiry instead of the endpoint 502ing
RANDOM_POOL_STALE_KEY = build_key("random", "pool", "stale")
RANDOM_POOL_LOCK_KEY = build_key("random", "pool", "lock")

# Loop-scoped like clients/musicbrainz.py's _mb_lock: a fresh lock per running
# loop, since asyncio.Lock is not safe to reuse across loops (tests run each
# under a new one)
_random_cache_lock: asyncio.Lock | None = None
_random_cache_lock_loop = None


def _get_random_cache_lock() -> asyncio.Lock:
    global _random_cache_lock, _random_cache_lock_loop
    loop = asyncio.get_running_loop()
    if _random_cache_lock is None or _random_cache_lock_loop is not loop:
        _random_cache_lock = asyncio.Lock()
        _random_cache_lock_loop = loop
    return _random_cache_lock


async def _build_random_pool() -> list[dict]:
    from clients.musicbrainz import mb_fetch

    letter = random.choice("abcdefghijklmnopqrstuvwxyz")
    offset = random.randint(0, 399)
    url = (
        f"{RANDOM_MB_BASE}/recording"
        f"?query=recording:{letter}*"
        f"&offset={offset}&limit=25"
        f"&inc=artist-credits+releases&fmt=json"
    )
    res = await mb_fetch(url)
    if not res.is_success:
        raise ValueError(f"MusicBrainz responded with {res.status_code}")
    recordings = res.json().get("recordings", [])
    pool = []
    for r in recordings:
        credits = r.get("artist-credit") or []
        credit = credits[0] if credits else None
        artist = (
            credit.get("name")
            or (credit.get("artist") or {}).get("name")
            or "Unknown"
            if credit
            else "Unknown"
        )
        artist_mbid = (
            (credit.get("artist") or {}).get("id", "") if credit else ""
        )
        releases = [
            {"mbid": rel["id"], "title": rel["title"], "date": rel.get("date")}
            for rel in (r.get("releases") or [])
        ]
        pool.append(
            {
                "mbid": r["id"],
                "title": r["title"],
                "artist": artist,
                "artistMbid": artist_mbid,
                "durationMs": r.get("length"),
                "firstReleaseDate": r.get("first-release-date"),
                "releases": releases,
            }
        )
    return pool


async def _enrich_track(track: dict) -> dict:
    from clients.streaming import get_streaming_links

    streaming = await get_streaming_links(track["artist"], track["title"])
    return {
        **track,
        "streaming": {
            "appleMusic": streaming.apple_music,
            "preview": streaming.preview,
            "youtubeVideoId": streaming.youtube_video_id,
            "spotify": streaming.spotify,
            "artwork": streaming.artwork,
        },
    }


# Rebuilds the pool, or returns the stale copy when another worker is already
# rebuilding it. The in-process lock is taken first so requests in this
# process queue behind one another rather than all contending for the Redis
# lock at once
async def _refresh_random_pool(cache: AsyncFallbackCache) -> list[dict] | None:
    async with _get_random_cache_lock():
        # Re-check: another task may have populated the pool while this one
        # waited for the lock, which is the same double-checked pattern the
        # sync implementation used
        pool = await cache.get_json(RANDOM_POOL_KEY)
        if pool is not None:
            return pool

        token = await cache.acquire_refresh_slot(
            RANDOM_POOL_LOCK_KEY, RANDOM_POOL_LOCK_TTL_S
        )
        if not token:
            return await cache.get_json(RANDOM_POOL_STALE_KEY)

        try:
            pool = await _build_random_pool()
        except Exception:
            logger.error(
                "Failed to refresh random pool from MusicBrainz",
                exc_info=True,
            )
            return await cache.get_json(RANDOM_POOL_STALE_KEY)
        else:
            await cache.set_json(RANDOM_POOL_KEY, pool, RANDOM_CACHE_TTL_S)
            await cache.set_json(
                RANDOM_POOL_STALE_KEY, pool, TTL_RANDOM_POOL_STALE
            )
            return pool
        finally:
            # Released only after the writes above, so another worker finding
            # the lock free also finds the value it was waiting for. Released
            # by token, so a refresh that outran the lock TTL cannot delete
            # the lock the next worker has already taken
            await cache.release_refresh_slot(RANDOM_POOL_LOCK_KEY, token)


@router.get("/random/")
async def random_tracks(response: Response) -> dict:
    cache = get_async_view_cache()
    pool = await cache.get_json(RANDOM_POOL_KEY)
    if pool is None:
        pool = await _refresh_random_pool(cache)

    # None - nothing usable was ever fetched. An empty list - the fetch
    # worked and MusicBrainz simply had nothing, which stays a 200 with no
    # tracks as it did before
    if pool is None:
        response.status_code = 502
        return {"error": "Failed to fetch tracks from MusicBrainz"}

    selected = random.sample(pool, min(RANDOM_RESPONSE_LIMIT, len(pool)))
    enriched = await asyncio.gather(*[_enrich_track(t) for t in selected])
    return {"tracks": list(enriched)}
