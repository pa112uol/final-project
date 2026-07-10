import asyncio
import logging
import os
import httpx
from .http import get_client

LB_BASE = "https://api.listenbrainz.org/1"

logger = logging.getLogger(__name__)


def _lb_client():
    kwargs = dict(
        timeout=15,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
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
        if not res.is_success:
            return []
        data = res.json()
        tag_block = data.get(mbid, {}).get("tag")
        if not tag_block:
            return []
        entries = (
            (tag_block.get("recording") or [])
            + (tag_block.get("artist") or [])
            + (tag_block.get("release_group") or [])
        )
        merged = {}
        for entry in entries:
            name = entry.get("tag", "").lower().strip()
            count = entry.get("count", 0)
            if name:
                merged[name] = merged.get(name, 0) + count
        return [{"name": k, "count": v} for k, v in merged.items()]
    except Exception:
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
