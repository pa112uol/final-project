from .http import get_client
from .musicbrainz import mb_fetch

MB_BASE = "https://musicbrainz.org/ws/2"
CAA_BASE = "https://coverartarchive.org"


async def _release_mbids_for_recording(recording_mbid: str) -> list[str]:
    try:
        res = await mb_fetch(
            f"{MB_BASE}/recording/{recording_mbid}",
            params={"inc": "releases", "fmt": "json"},
        )
        if not res.is_success:
            return []
        return [r["id"] for r in res.json().get("releases") or []]
    except Exception:
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
                url = (
                    t.get("small")
                    or t.get("250")
                    or t.get("large")
                    or image.get("image")
                )
                # Cover Art Archive returns http:// URLs even when queried over
                # https; upgrade so images aren't blocked as mixed content
                return url.replace("http://", "https://", 1) if url else None
        return None
    except Exception:
        return None


# Skips the MusicBrainz release lookup when the caller already resolved one.
# Falls back to full discovery if that release has no front art
async def fetch_cover_art_url(
    recording_mbid: str, release_mbid: str | None = None
) -> str | None:
    if release_mbid:
        url = await _front_art_url(release_mbid)
        if url:
            return url

    for candidate_mbid in await _release_mbids_for_recording(recording_mbid):
        if candidate_mbid == release_mbid:
            continue
        url = await _front_art_url(candidate_mbid)
        if url:
            return url
    return None
