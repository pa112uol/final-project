import asyncio
from .http import get_client

MB_BASE = "https://musicbrainz.org/ws/2"
CAA_BASE = "https://coverartarchive.org"


async def _release_mbids_for_recording(recording_mbid: str) -> list[str]:
    for attempt in range(2):
        try:
            res = await get_client("coverart-mb", timeout=8).get(
                f"{MB_BASE}/recording/{recording_mbid}",
                params={"inc": "releases", "fmt": "json"},
            )
            if res.status_code in (429, 503):
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                return []
            if not res.is_success:
                return []
            return [r["id"] for r in res.json().get("releases") or []]
        except Exception:
            return []
    return []


async def _front_art_url(release_mbid: str) -> str | None:
    try:
        res = await get_client("coverart", timeout=8).get(
            f"{CAA_BASE}/release/{release_mbid}",
            follow_redirects=True,
        )
        if not res.is_success:
            return None
        for image in res.json().get("images", []):
            if image.get("front"):
                t = image.get("thumbnails", {})
                return t.get("small") or t.get("250") or t.get("large") or image.get("image")
        return None
    except Exception:
        return None


async def fetch_cover_art_url(recording_mbid: str) -> str | None:
    for release_mbid in await _release_mbids_for_recording(recording_mbid):
        url = await _front_art_url(release_mbid)
        if url:
            return url
    return None
