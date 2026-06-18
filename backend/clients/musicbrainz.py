import re
import logging
from .http import get_client

MB_BASE = "https://musicbrainz.org/ws/2"
logger = logging.getLogger(__name__)

_NOISE_RE = re.compile(
    r'\s*[\(\[]\s*(?:official\s+(?:music\s+)?video|lyrics?|hd|remaster(?:ed)?|'
    r'audio|live|explicit|clean|radio\s+edit)\s*[\)\]]',
    re.IGNORECASE,
)
_FEAT_RE = re.compile(r'\s+feat\.?\s+.*$', re.IGNORECASE)
_QUOTES_RE = re.compile(r'^(["\'])(.+)\1$')
_MULTI_SPACE_RE = re.compile(r'\s{2,}')
_MB_ESCAPE_RE = re.compile(r'([\(\)\[\]{}\^~*?:\\/+\-&|!])')
_BY_RE = re.compile(r'\s+by\s+', re.IGNORECASE)
_DASH_RE = re.compile(r'\s*[–—‒/:\\-]\s*')

_FIXED_FILTERS = (
    "status:official"
    " AND (primarytype:album OR primarytype:single OR primarytype:ep)"
    " AND -secondarytype:live"
    " AND -secondarytype:interview"
    " AND -secondarytype:video"
    " AND -secondarytype:spokenword"
    " AND -secondarytype:audiobook"
    " AND -recording:live"
    " AND -comment:live"
    " AND -video:true"
)


def _clean(s: str) -> str:
    s = s.strip()
    m = _QUOTES_RE.match(s)
    if m:
        s = m.group(2)
    s = _NOISE_RE.sub("", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def _escape_mb(s: str) -> str:
    return _MB_ESCAPE_RE.sub(r"\\\1", s)


def _parse_artist_track(q: str) -> tuple[str | None, str]:
    parts = _DASH_RE.split(q, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()

    # "Track by Artist" - use the last " by " so that titles like
    # "By The Way by RHCP" resolve correctly.
    matches = list(_BY_RE.finditer(q))
    if matches:
        m = matches[-1]
        artist = q[m.end():].strip()
        track = q[: m.start()].strip()
        if artist and track:
            return artist, track

    return None, q.strip()


def _build_query(q: str) -> str:
    q = _clean(q)
    q = _FEAT_RE.sub("", q).strip()

    artist, title = _parse_artist_track(q)
    esc_title = _escape_mb(title)

    if artist:
        esc_artist = _escape_mb(artist)
        forward = f'recording:("{esc_title}") AND artistname:("{esc_artist}")'
        reversed_ = f'recording:("{esc_artist}") AND artistname:("{esc_title}")'
        title_fuzzy = " AND ".join(f"recording:{_escape_mb(w)}~" for w in title.split() if w)
        core = f'({forward}) OR ({reversed_}) OR ({title_fuzzy} AND artistname:{esc_artist}~)'
    else:
        words = title.split()
        phrase = f'recording:("{esc_title}")'
        fuzzy = " AND ".join(f"recording:{_escape_mb(w)}~" for w in words if w)
        if len(words) == 1:
            esc_word = _escape_mb(words[0])
            artist_branch = f'artistname:"{esc_word}" AND -recording:({esc_word}~)'
            core = f'({phrase} OR {fuzzy}) OR ({artist_branch})'
        else:
            core = f'{phrase} OR ({fuzzy})'

    return f'({core}) AND {_FIXED_FILTERS}'


def _blend_score(
    q_artist: str | None,
    q_title: str,
    rec_title: str,
    rec_artist: str,
    mb_score: int,
) -> float:
    score = float(mb_score)

    if not q_artist:
        # Penalise self-referential titles, the query word appears in both the
        # artist name and a title much longer than the query (interview or
        # compilation titles often do this).
        q_words = q_title.lower().split()
        if (
            len(q_words) == 1
            and q_words[0] in rec_artist.lower()
            and q_words[0] in rec_title.lower()
            and len(rec_title.split()) >= len(q_words) + 2
        ):
            score *= 0.5

    return score


async def search_tracks(q: str) -> list:
    cleaned = _clean(q)
    if not cleaned:
        return []

    lucene_query = _build_query(cleaned)
    logger.debug("MB search query: %s", lucene_query)

    q_artist, q_title = _parse_artist_track(cleaned)
    q_title = _FEAT_RE.sub("", q_title).strip()

    try:
        res = await get_client("mb-search", timeout=10).get(
            f"{MB_BASE}/recording",
            params={"query": lucene_query, "fmt": "json", "limit": 100},
        )
        if not res.is_success:
            logger.warning("MB search HTTP %s", res.status_code)
            return []
        recordings = res.json().get("recordings") or []
    except Exception:
        logger.exception("MB search failed")
        return []

    seen_mbids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    results = []

    for r in recordings:
        mbid = r.get("id")
        if not mbid:
            continue

        credits = r.get("artist-credit") or []
        artist_name = credits[0].get("name", "") if credits else ""
        title = r.get("title", "")

        pair = (title.lower(), artist_name.lower())
        if mbid in seen_mbids or pair in seen_pairs:
            continue
        seen_mbids.add(mbid)
        seen_pairs.add(pair)

        releases = r.get("releases") or []
        first_release = releases[0] if releases else None
        release_type = (
            first_release.get("release-group", {}).get("primary-type")
            if first_release
            else None
        )
        album = first_release.get("title") if first_release else None
        raw_date = (
            r.get("first-release-date")
            or (first_release.get("date") if first_release else None)
            or ""
        )
        year = raw_date[:4] or None

        mb_score = int(r.get("score") or 0)
        blended = _blend_score(q_artist, q_title, title, artist_name, mb_score)

        results.append({
            "mbid": mbid,
            "title": title,
            "artist": artist_name,
            "album": album,
            "release_type": release_type,
            "year": year,
            "score": blended,
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
