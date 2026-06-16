import re
import logging
from .http import get_client

MB_BASE = "https://musicbrainz.org/ws/2"

logger = logging.getLogger(__name__)


def _escape_mb(s: str) -> str:
    return re.sub(r'[+\-&|!(){}[\]^"~*?:\\/]', r"\\\g<0>", s)


def _build_mb_query(q: str) -> str:
    dash_match = re.match(r"^(.+?)\s+-\s+(.+)$", q)
    if dash_match:
        artist_part = _escape_mb(dash_match.group(1).strip())
        track_part = _escape_mb(dash_match.group(2).strip())
        return f"recording:({track_part})^2 AND artist:({artist_part})"
    escaped = _escape_mb(q)
    return f"recording:({escaped})^2 AND artist:({escaped})"


async def search_tracks(q: str) -> list:
    query = _build_mb_query(q)
    try:
        res = await get_client("mb-search", timeout=10).get(
            f"{MB_BASE}/recording",
            params={"query": query, "limit": "15", "fmt": "json"},
        )
        if not res.is_success:
            return []
        data = res.json()
        recordings = data.get("recordings", [])
        seen = set()
        results = []
        for r in recordings:
            if not r.get("id"):
                continue
            credits = r.get("artist-credit") or []
            artist = credits[0].get("name", "") if credits else ""
            key = f"{r['title'].lower()}|{artist.lower()}"
            if key in seen:
                continue
            seen.add(key)
            results.append({"mbid": r["id"], "title": r["title"], "artist": artist})
            if len(results) == 10:
                break
        return results
    except Exception:
        return []


async def resolve_canonical_mbid(mbid: str) -> str:
    try:
        res = await get_client("mb-search", timeout=10).get(
            f"{MB_BASE}/recording/{mbid}",
            params={"fmt": "json"},
        )
        if not res.is_success:
            return mbid
        data = res.json()
        return data.get("id", mbid)
    except Exception:
        return mbid
