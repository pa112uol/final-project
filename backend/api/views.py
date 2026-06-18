import asyncio
import random
import time
import logging
import threading
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Django view."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
    except RuntimeError:
        pass
    return asyncio.run(coro)


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
        }
        for t in tracks
    ]
    return JsonResponse({"results": results})


_coverart_cache: dict = {}


@require_GET
def coverart(request):
    mbid = (request.GET.get("mbid") or "").strip()
    if not mbid:
        return JsonResponse({"error": "mbid required"}, status=400)

    if mbid in _coverart_cache:
        url = _coverart_cache[mbid]
        if not url:
            return JsonResponse({"error": "No cover art found"}, status=404)
        return JsonResponse({"url": url})

    from clients.coverart import fetch_cover_art_url

    url = _run_async(fetch_cover_art_url(mbid))
    if url:
        _coverart_cache[mbid] = url
    if not url:
        return JsonResponse({"error": "No cover art found"}, status=404)
    return JsonResponse({"url": url})


RANDOM_MB_BASE = "https://musicbrainz.org/ws/2"
RANDOM_RESPONSE_LIMIT = 5
RANDOM_CACHE_TTL_S = 60

random_cache: list[dict] | None = None
random_cache_expires: float = 0.0
random_cache_lock = threading.Lock()


async def _build_random_pool() -> list[dict]:
    from clients.mb import mb_fetch

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
        },
    }


@require_GET
def random_tracks(request):
    global random_cache, random_cache_expires

    now = time.time()
    if random_cache is None or now > random_cache_expires:
        with random_cache_lock:
            if random_cache is None or now > random_cache_expires:
                try:
                    pool = _run_async(_build_random_pool())
                    random_cache = pool
                    random_cache_expires = now + RANDOM_CACHE_TTL_S
                except Exception:
                    logger.error(
                        "Failed to refresh random pool from MusicBrainz",
                        exc_info=True,
                    )
                    if random_cache is None:
                        return JsonResponse(
                            {
                                "error": "Failed to fetch tracks from MusicBrainz"
                            },
                            status=502,
                        )

    selected = random.sample(
        random_cache, min(RANDOM_RESPONSE_LIMIT, len(random_cache))
    )

    async def _enrich_all():
        return list(await asyncio.gather(*[_enrich_track(t) for t in selected]))

    enriched = _run_async(_enrich_all())
    return JsonResponse({"tracks": list(enriched)})
