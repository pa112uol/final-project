import asyncio
import random
import time
import logging
import threading
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_GET

from caching.config import (
    NEGATIVE_TTL_S,
    RANDOM_POOL_LOCK_TTL_S,
    TTL_COVERART,
    TTL_RANDOM_POOL,
    TTL_RANDOM_POOL_STALE,
)
from caching.keys import build_key
from caching.local import get_view_cache

logger = logging.getLogger(__name__)


# Background loop for running async code from sync Django views. This is a
# singleton per-process, so it is shared across all threads in the worker
_background_loop: asyncio.AbstractEventLoop | None = None
_background_loop_thread: threading.Thread | None = None
_background_loop_lock = threading.Lock()


def _get_background_loop() -> asyncio.AbstractEventLoop:
    global _background_loop, _background_loop_thread
    with _background_loop_lock:
        if _background_loop is None or _background_loop.is_closed():
            _background_loop = asyncio.new_event_loop()
            _background_loop_thread = threading.Thread(
                target=_background_loop.run_forever,
                name="views-async-loop",
                daemon=True,
            )
            _background_loop_thread.start()
        return _background_loop


# Runs a coroutine from a sync Django view, blocking the calling thread until it
# completes
def _run_async(coro):
    loop = _get_background_loop()
    if threading.current_thread() is _background_loop_thread:
        raise RuntimeError(
            "_run_async called from the background loop, await the coroutine"
        )
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


@require_GET
def recommendations(request):
    start_ms = int(time.time() * 1000)
    req_id = "".join(
        random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=5)
    )

    def log(phase, data):
        logger.info(
            "[REC:%s %s +%dms] %s",
            phase,
            req_id,
            int(time.time() * 1000) - start_ms,
            data,
        )

    api_key = settings.LASTFM_API_KEY
    if not api_key:
        return JsonResponse({"error": "LASTFM_API_KEY not set"}, status=500)

    mbids = request.GET.getlist("mbid")
    titles = request.GET.getlist("title")
    artists = request.GET.getlist("artist")
    mood_raw = request.GET.get("mood", "").lower().strip() or None
    novelty_raw = request.GET.get("novelty", "0")

    try:
        novelty = float(novelty_raw)
    except (ValueError, TypeError):
        novelty = 0.0
    novelty = max(0.0, min(1.0, novelty))

    if not mbids:
        return JsonResponse({"error": "No seed tracks provided"}, status=400)

    from recommendations.tags import MOOD_TAGS

    if mood_raw and mood_raw not in MOOD_TAGS:
        return JsonResponse(
            {
                "error": f"Unknown mood. Valid values: {', '.join(MOOD_TAGS.keys())}"
            },
            status=400,
        )

    seeds = [
        {
            "mbid": mbid,
            "title": (titles[i] if i < len(titles) else "").lower().strip(),
            "artist": (artists[i] if i < len(artists) else "").lower().strip(),
        }
        for i, mbid in enumerate(mbids)
    ]

    log("input", {"seeds": seeds, "mood": mood_raw, "novelty": novelty})

    from recommendations.index import get_recommendations

    try:
        tracks = _run_async(
            get_recommendations(seeds, api_key, mood_raw, novelty)
        )
    except Exception as err:
        logger.error("[REC] pipeline error: %s", err, exc_info=True)
        return JsonResponse(
            {"error": "Failed to fetch recommendations"}, status=500
        )

    log(
        "result",
        {
            "tracksReturned": len(tracks),
            "totalMs": int(time.time() * 1000) - start_ms,
        },
    )

    return JsonResponse({"tracks": [t.to_dict() for t in tracks]})


@require_GET
def search(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})

    from clients.musicbrainz import search_tracks

    tracks = _run_async(search_tracks(q))
    results = [
        {
            "type": "track",
            "mbid": t["mbid"],
            "label": t["title"],
            "sub": t["artist"],
            "album": t.get("album"),
            "releaseType": t.get("release_type"),
            "year": t.get("year"),
        }
        for t in tracks
    ]
    return JsonResponse({"results": results})


# Lazily resolves one track's MusicBrainz recording data (duration, album,
# release date). Caching/TTL is handled by the cached client it calls
@require_GET
def recording(request):
    title = (request.GET.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "title required"}, status=400)

    mbid = (request.GET.get("mbid") or "").strip()
    artist = (request.GET.get("artist") or "").strip()

    from clients.musicbrainz import EMPTY_RECORDING
    from recommendations.index import resolve_recording
    from recommendations.types import resolved_to_dict

    try:
        resolved = _run_async(resolve_recording(mbid, title, artist))
    except Exception:
        logger.error(
            "[recording] resolution failed for %r by %r",
            title,
            artist,
            exc_info=True,
        )
        resolved = {"mbid": mbid, **EMPTY_RECORDING}

    return JsonResponse(resolved_to_dict(resolved))


COVERART_NAMESPACE = "coverart"
# A "no cover art" result is often a transient failure (rate limit, timeout)
# rather than a real fact about the recording, so it's only cached briefly.
# A found url is cached for a long time since that data doesn't change.
COVERART_NEGATIVE_TTL_S = NEGATIVE_TTL_S

# The url is stored inside an envelope so a cached "no cover art" can be told
# apart from a cache miss
_COVERART_URL_FIELD = "url"


@require_GET
def coverart(request):
    mbid = (request.GET.get("mbid") or "").strip()
    if not mbid:
        return JsonResponse({"error": "mbid required"}, status=400)

    # Optional release the caller already resolved, so fetch_cover_art_url can skip its own lookup.
    release_mbid = (request.GET.get("releaseMbid") or "").strip() or None

    cache = get_view_cache()
    key = build_key(COVERART_NAMESPACE, mbid)
    cached = cache.get_json(key)
    if isinstance(cached, dict) and _COVERART_URL_FIELD in cached:
        return _coverart_response(cached[_COVERART_URL_FIELD])

    from clients.coverart import fetch_cover_art_url

    url = _run_async(fetch_cover_art_url(mbid, release_mbid))
    cache.set_json(
        key,
        {_COVERART_URL_FIELD: url},
        TTL_COVERART if url else COVERART_NEGATIVE_TTL_S,
    )
    return _coverart_response(url)


# A missing url is a 404 rather than an empty 200, which is what the frontend's
# CoverArt component distinguishes on
def _coverart_response(url):
    if not url:
        return JsonResponse({"error": "No cover art found"}, status=404)
    return JsonResponse({"url": url})


RANDOM_MB_BASE = "https://musicbrainz.org/ws/2"
RANDOM_RESPONSE_LIMIT = 5
RANDOM_CACHE_TTL_S = TTL_RANDOM_POOL

RANDOM_POOL_KEY = build_key("random", "pool")
# When a refresh fails there is nothing left under RANDOM_POOL_KEY to fall back on,
# so this preserves the old behaviour where the stale Python list stayed usable
# past its expiry instead of the endpoint 502ing
RANDOM_POOL_STALE_KEY = build_key("random", "pool", "stale")
RANDOM_POOL_LOCK_KEY = build_key("random", "pool", "lock")

# Stops threads withi one worker from racing, which is what the original threading.Lock guarded.
# The Redis lock handles the cross-process case the original could not.
random_cache_lock = threading.Lock()


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
# rebuilding it. The in-process lock is taken first so threads in this worker
# queue behind one another rather than all contending for the Redis lock
def _refresh_random_pool(cache) -> list[dict] | None:
    with random_cache_lock:
        # Re-check- another thread may have populated the pool while this one
        # waited for the lock, which is the same double checked pattern the
        # previous implementation used.
        pool = cache.get_json(RANDOM_POOL_KEY)
        if pool is not None:
            return pool

        token = cache.acquire_refresh_slot(
            RANDOM_POOL_LOCK_KEY, RANDOM_POOL_LOCK_TTL_S
        )
        if not token:
            return cache.get_json(RANDOM_POOL_STALE_KEY)

        try:
            pool = _run_async(_build_random_pool())
        except Exception:
            logger.error(
                "Failed to refresh random pool from MusicBrainz",
                exc_info=True,
            )
            return cache.get_json(RANDOM_POOL_STALE_KEY)
        else:
            cache.set_json(RANDOM_POOL_KEY, pool, RANDOM_CACHE_TTL_S)
            cache.set_json(RANDOM_POOL_STALE_KEY, pool, TTL_RANDOM_POOL_STALE)
            return pool
        finally:
            # Released only after the writes above, so another worker finding
            # the lock free also finds the value it was waiting for. Released by
            # token, so a refresh that outran the lock TTL cannot delete the
            # lock the next worker has already taken
            cache.release_refresh_slot(RANDOM_POOL_LOCK_KEY, token)


@require_GET
def random_tracks(request):
    cache = get_view_cache()
    pool = cache.get_json(RANDOM_POOL_KEY)
    if pool is None:
        pool = _refresh_random_pool(cache)

    # None - nothing usable was ever fetched. An empty list - the fetch
    # worked and MusicBrainz simply had nothing, which stays a 200 with no
    # tracks as it did before
    if pool is None:
        return JsonResponse(
            {"error": "Failed to fetch tracks from MusicBrainz"},
            status=502,
        )

    selected = random.sample(pool, min(RANDOM_RESPONSE_LIMIT, len(pool)))

    async def _enrich_all():
        return list(await asyncio.gather(*[_enrich_track(t) for t in selected]))

    enriched = _run_async(_enrich_all())
    return JsonResponse({"tracks": list(enriched)})
