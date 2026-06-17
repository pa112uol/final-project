import re
import logging
from rapidfuzz import fuzz
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

# Strip feat./ft./featuring from the track component before title matching
_FEAT_RE = re.compile(r"\s+(?:ft\.?|feat\.?|featuring)\s+.+$", re.IGNORECASE)

_SPECIAL = re.compile(r'[+\-&|!(){}[\]^"~*?:\\/]')

# Minimum blended confidence to keep a result (0-100)
_THRESHOLD = 45

# Blend weights: rf_score (rapidfuzz similarity), mb_score (Lucene relevance),
# age_score (older = higher)
_RF_WEIGHT = 0.50
_MB_WEIGHT = 0.40
_AGE_WEIGHT = 0.10

# Normalisation base: 75 years (1950 => 100, 2025 => 0)
_AGE_SPAN = 75


def _escape_mb(s: str) -> str:
    return _SPECIAL.sub(r"\\\g<0>", s)


def _clean(q: str) -> str:
    q = q.strip()
    q = re.sub(r'^["\']|["\']$', "", q)
    q = _NOISE_RE.sub("", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _parse_artist_track(q: str):
    dash = re.match(r"^(.+?)\s+-\s+(.+)$", q)
    if dash:
        return dash.group(1).strip(), dash.group(2).strip()

    # Greedy first group: "By The Way by RHCP" -> track="By The Way", artist="RHCP"
    by_m = re.match(r"^(.+)\s+by\s+(.+)$", q, re.IGNORECASE)
    if by_m:
        return by_m.group(2).strip(), by_m.group(1).strip()

    return None, q


def _build_query(q: str) -> str:
    artist, track = _parse_artist_track(q)

    if artist:
        a = _escape_mb(artist)
        t = _escape_mb(_FEAT_RE.sub("", track).strip())
        return f'("{t}" AND artistname:"{a}") OR ("{a}" AND artistname:"{t}")'
    else:
        e = _escape_mb(_FEAT_RE.sub("", q).strip())
        words = e.split()
        fuzzy = " ".join(f"{w}~" for w in words)
        if len(words) == 1:
            # Single-word queries use the artist-only branch to surface songs,
            # not self-titled recordings
            return f'(+artistname:"{e}" -recording:({fuzzy}))'
        return (
            f'(recording:({fuzzy}) AND artistname:({fuzzy})) OR '
            f'recording:("{e}") OR '
            f'recording:({fuzzy}) OR '
            f'artistname:({fuzzy})'
        )


def _rapidfuzz_score(query: str, query_artist: str | None, query_track: str,
                     result_title: str, result_artist: str) -> float:
    t_score = fuzz.token_sort_ratio(query_track.lower(), result_title.lower())

    if query_artist:
        a_score = fuzz.token_sort_ratio(query_artist.lower(), result_artist.lower())
        return (t_score + a_score) / 2

    # For plain queries, score against title, combined title+artist, and artist (0.75x penalty) and take the max
    combined = f"{result_title} {result_artist}".lower()
    combined_score = fuzz.token_sort_ratio(query.lower(), combined)
    a_score = fuzz.token_sort_ratio(query.lower(), result_artist.lower()) * 0.75
    return max(t_score, combined_score, a_score)


def _age_score(first_release_date: str) -> float:
    # Older recordings score higher (0-100). Missing dates return neutral 50
    if not first_release_date:
        return 50.0
    try:
        year = int(first_release_date[:4])
        return max(0.0, min(100.0, (2025 - year) / _AGE_SPAN * 100))
    except (ValueError, IndexError):
        return 50.0


async def search_tracks(q: str) -> list:
    q = _clean(q)
    if not q:
        return []

    query = _build_query(q)
    logger.debug("MB search query: %s", query)

    # Single-word artist queries need 50 results because proper songs are outranked by self-titled recordings
    is_single_word = len(q.split()) == 1
    limit = "50" if is_single_word else "20"

    try:
        res = await get_client("mb-search", timeout=10).get(
            f"{MB_BASE}/recording",
            params={"query": query, "limit": limit, "fmt": "json"},
        )
        if not res.is_success:
            logger.warning("MB search HTTP %s", res.status_code)
            return []
        recordings = res.json().get("recordings") or []
    except Exception:
        logger.exception("MB search failed")
        return []

    query_artist, query_track = _parse_artist_track(q)

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

        rf_score = _rapidfuzz_score(q, query_artist, query_track, r["title"], artist)
        mb_score = float(r.get("score") or 0)
        age = _age_score(r.get("first-release-date", ""))
        score = rf_score * _RF_WEIGHT + mb_score * _MB_WEIGHT + age * _AGE_WEIGHT

        # Penalise recordings where the band name is embedded in a longer title (interviews, remixes)
        q_words = len(q.split())
        title_words = len(r["title"].split())
        if (not query_artist
                and fuzz.token_sort_ratio(q.lower(), artist.lower()) > 80
                and q.lower() in r["title"].lower()
                and title_words >= q_words + 1):
            score *= 0.75

        if score < _THRESHOLD:
            continue

        results.append({
            "mbid": mbid,
            "title": r["title"],
            "artist": artist,
            "score": score,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


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
