import re
import logging
from .http import get_client

MB_BASE = "https://musicbrainz.org/ws/2"
logger = logging.getLogger(__name__)

# Noise suffixes users paste from YouTube or streaming titles
_NOISE_RE = re.compile(
    r"\s*[\(\[]"
    r"(?:official\s*(?:music\s*)?(?:video|audio|lyric(?:s)?|visualizer)?"
    r"|lyrics?|hd|4k|full\s*song|audio|video|mv|remaster(?:ed)?|live|acoustic)"
    r"[\)\]]",
    re.IGNORECASE,
)

# "feat." / "ft." / "featuring" strip from track component before title matching
_FEAT_RE = re.compile(r"\s+(?:ft\.?|feat\.?|featuring)\s+.+$", re.IGNORECASE)

_SPECIAL = re.compile(r'[+\-&|!(){}[\]^"~*?:\\/]')


def _escape_mb(s: str) -> str:
    return _SPECIAL.sub(r"\\\g<0>", s)


def _clean(q: str) -> str:
    """Normalise raw user input before query building."""
    q = q.strip()
    q = re.sub(r'^["\']|["\']$', "", q)   # strip outer quotes
    q = _NOISE_RE.sub("", q)              # strip "(Official Video)" etc.
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _parse_artist_track(q: str):
    """
    Return (artist, track) when a separator is present, else (None, q).

    Handles:
      Artist - Track   (dash with spaces, most common)
      Track by Artist  (greedy "by" so "By The Way by RHCP" parses correctly)
    """
    dash = re.match(r"^(.+?)\s+-\s+(.+)$", q)
    if dash:
        return dash.group(1).strip(), dash.group(2).strip()

    # Greedy first group: "By The Way by RHCP" → track="By The Way", artist="RHCP"
    by_m = re.match(r"^(.+)\s+by\s+(.+)$", q, re.IGNORECASE)
    if by_m:
        return by_m.group(2).strip(), by_m.group(1).strip()

    return None, q


def _build_query(q: str) -> str:
    artist, track = _parse_artist_track(q)

    if artist:
        a = _escape_mb(artist)
        t = _escape_mb(_FEAT_RE.sub("", track).strip())
        parts = [
            # Highest confidence: exact phrase, correct Artist - Track order
            f'(recording:("{t}")^3 AND artist:("{a}")^2)',
            # Token match, correct order
            f'(recording:({t})^2 AND artist:({a}))',
            # Reversed order fallback (user may have typed Track - Artist)
            f'(recording:("{a}") AND artist:("{t}"))',
        ]
    else:
        e = _escape_mb(_FEAT_RE.sub("", q).strip())
        words = e.split()
        parts = [
            # Cross-field: each field must match ≥1 token - works for "radiohead creep"
            f'(recording:({e})^2 AND artist:({e}))',
            # Phrase match for pure track names - works for "bohemian rhapsody"
            f'recording:("{e}")^2',
            # Token fallback for single-artist or partial name queries
            f'recording:({e})',
        ]
        # Fuzzy for short queries (≤2 words) to handle common typos
        if 1 <= len(words) <= 2:
            fuzzy = " ".join(f"{w}~" for w in words)
            parts.append(f'(recording:({fuzzy}) AND artist:({fuzzy}))')

    return " OR ".join(parts)


async def search_tracks(q: str) -> list:
    q = _clean(q)
    if not q:
        return []

    query = _build_query(q)
    logger.debug("MB search query: %s", query)

    try:
        res = await get_client("mb-search", timeout=10).get(
            f"{MB_BASE}/recording",
            params={"query": query, "limit": "20", "fmt": "json"},
        )
        if not res.is_success:
            logger.warning("MB search HTTP %s", res.status_code)
            return []
        recordings = res.json().get("recordings") or []
    except Exception:
        logger.exception("MB search failed")
        return []

    seen_mbid: set[str] = set()
    seen_key: set[str] = set()
    results: list[dict] = []

    for r in recordings:
        mbid = r.get("id")
        if not mbid or mbid in seen_mbid:
            continue
        credits = r.get("artist-credit") or []
        artist = credits[0].get("name", "") if credits else ""
        key = f"{r['title'].lower()}|{artist.lower()}"
        if key in seen_key:
            seen_mbid.add(mbid)
            continue
        seen_mbid.add(mbid)
        seen_key.add(key)
        results.append({
            "mbid": mbid,
            "title": r["title"],
            "artist": artist,
            "score": int(r.get("score", 0)),
        })
        if len(results) == 10:
            break

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


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
