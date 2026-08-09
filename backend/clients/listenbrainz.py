import asyncio
import logging
import os
import httpx
from .http import get_client

LB_BASE = "https://api.listenbrainz.org/1"

# The endpoint returns tags at three scopes whose counts are not comparable:
# artist tags accumulate votes across a whole discography, so summing them raw
# makes a seed profile describe the artist rather than the track. For
# "Californication" 22 of the 31 "funk rock" votes are artist-level and 1 the
# recording's, while the song's own character (mellow, melancholic) sits at
# 1-2. Down-weighting is a balance rather than a minimisation, since recording
# counts are sparse enough that discounting artist scope too hard leaves one
# tag dominating a thin profile: at 0.15 this query lost "grunge" and returned
# AC/DC and Kiss, whereas 0.3 keeps each seed's distinctive tags and cuts
# artist-bleed like "rap rock" to a minor contribution.
TAG_LEVEL_WEIGHTS = {
    "recording": 1.0,
    "release_group": 0.4,
    "artist": 0.3,
}

logger = logging.getLogger(__name__)


def _lb_client():
    kwargs = dict(
        timeout=15,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    token = os.environ.get("LISTENBRAINZ_API_KEY")
    if token:
        kwargs["headers"] = {"Authorization": f"Token {token}"}
    return get_client("listenbrainz", **kwargs)


async def fetch_recording_tags(mbid: str) -> list:
    if not mbid:
        return []
    try:
        res = await _lb_client().get(
            f"{LB_BASE}/metadata/recording/",
            params={"recording_mbids": mbid, "inc": "tag"},
        )
        # An outage and a genuinely untagged recording both yield an empty tag
        # list, but they mean opposite things: the first silently halves a
        # two-source profile, the second is real data. Log which one happened
        # so a run's tag profile can be interpreted after the fact.
        if not res.is_success:
            logger.warning(
                "[listenbrainz] recording tags unavailable for %s: HTTP %s",
                mbid,
                res.status_code,
            )
            return []
        data = res.json()
        tag_block = data.get(mbid, {}).get("tag")
        if not tag_block:
            logger.info(
                "[listenbrainz] no tags for recording %s (endpoint healthy)",
                mbid,
            )
            return []
        merged = {}
        for level, weight in TAG_LEVEL_WEIGHTS.items():
            for entry in tag_block.get(level) or []:
                name = entry.get("tag", "").lower().strip()
                count = entry.get("count", 0)
                if name:
                    merged[name] = merged.get(name, 0) + count * weight
        return [{"name": k, "count": v} for k, v in merged.items()]
    except Exception as exc:
        logger.warning(
            "[listenbrainz] recording tags failed for %s: %s: %s",
            mbid,
            type(exc).__name__,
            exc,
        )
        return []


async def fetch_artist_top_recordings(artist_mbid: str, limit: int) -> list:
    for attempt in range(2):
        try:
            res = await _lb_client().get(
                f"{LB_BASE}/popularity/top-recordings-for-artist/{artist_mbid}",
            )
            if res.status_code == 429:
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                logger.warning(
                    "[lb] fetch_artist_top_recordings HTTP 429 for %s", artist_mbid
                )
                return []
            if not res.is_success:
                logger.warning(
                    "[lb] fetch_artist_top_recordings HTTP %d for %s",
                    res.status_code,
                    artist_mbid,
                )
                return []
            data = res.json()
            result = []
            for r in data[:limit]:
                if not (r.get("recording_mbid") and r.get("recording_name") and r.get("artist_mbids")):
                    continue
                result.append({
                    "mbid": r["recording_mbid"],
                    "title": r["recording_name"],
                    "artist_mbid": r["artist_mbids"][0] if r["artist_mbids"] else artist_mbid,
                    "duration_ms": r.get("length"),
                    "listen_count": r.get("total_listen_count", 0),
                    "user_count": r.get("total_user_count", 0),
                    "tags": [
                        t["tag"].lower()
                        for t in sorted(
                            r.get("tags") or [],
                            key=lambda t: t.get("count", 0),
                            reverse=True,
                        )
                    ],
                })
            return result
        except Exception as e:
            logger.error("[lb] fetch_artist_top_recordings failed: %s", e)
            return []
    return []


async def fetch_recording_popularity(mbids: list) -> dict:
    valid_mbids = [m for m in mbids if m]
    if not valid_mbids:
        return {}
    try:
        res = await _lb_client().post(
            f"{LB_BASE}/popularity/recording",
            json={"recording_mbids": valid_mbids},
            headers={"Content-Type": "application/json"},
        )
        if not res.is_success:
            logger.warning(
                "[lb] fetch_recording_popularity HTTP %d: %s",
                res.status_code,
                res.text[:200],
            )
            return {}
        data = res.json()
        result = {}
        for r in data:
            if r.get("total_listen_count") is not None:
                result[r["recording_mbid"]] = r["total_listen_count"]
        logger.info(
            "[lb] fetch_recording_popularity: %d/%d mbids returned data",
            len(result),
            len(valid_mbids),
        )
        return result
    except Exception as e:
        logger.error("[lb] fetch_recording_popularity failed: %s", e)
        return {}


async def fetch_artist_popularity(artist_mbids: list) -> dict:
    valid_mbids = [m for m in artist_mbids if m]
    if not valid_mbids:
        return {}
    try:
        res = await _lb_client().post(
            f"{LB_BASE}/popularity/artist",
            json={"artist_mbids": valid_mbids},
            headers={"Content-Type": "application/json"},
        )
        if not res.is_success:
            logger.warning(
                "[lb] fetch_artist_popularity HTTP %d: %s",
                res.status_code,
                res.text[:200],
            )
            return {}
        data = res.json()
        result = {}
        for r in data:
            if r.get("total_listen_count") is not None:
                result[r["artist_mbid"]] = r["total_listen_count"]
        logger.info(
            "[lb] fetch_artist_popularity: %d/%d mbids returned data",
            len(result),
            len(valid_mbids),
        )
        return result
    except Exception as e:
        logger.error("[lb] fetch_artist_popularity failed: %s", e)
        return {}
