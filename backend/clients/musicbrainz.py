import asyncio
import re
import logging
import time
import httpx
from caching.ratelimit import MB_SLOT_KEY, RedisRateLimiter
from .http import get_client

# MusicBrainz requires a meaningful User-Agent: App/Version (contact)
# https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
MB_BASE = "https://musicbrainz.org/ws/2"
MB_MIN_INTERVAL_S = 1.05
MB_RETRYABLE_STATUS_CODES = (429, 503)

# Transient transport faults worth a second attempt. Deliberately excludes
# httpx.ProtocolError and UnsupportedProtocol, which signal a bug in the
# request rather than upstream load, so retrying them just doubles the wait.
MB_RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)
MB_RETRY_BACKOFF_S = 0.5
MB_MAX_ATTEMPTS = 2
MB_TIMEOUT_S = 10

logger = logging.getLogger(__name__)

# Reserves the next slot in Redis so spacing holds across
# every worker and every request, not just within one event loop
_mb_limiter = RedisRateLimiter(MB_SLOT_KEY, MB_MIN_INTERVAL_S)

# In-process fallback for when Redis is unavailable
_mb_lock: asyncio.Lock | None = None
_mb_lock_loop = None
_last_request_time = 0.0


def _get_mb_lock() -> asyncio.Lock:
    global _mb_lock, _mb_lock_loop
    loop = asyncio.get_running_loop()
    if _mb_lock is None or _mb_lock_loop is not loop:
        _mb_lock = asyncio.Lock()
        _mb_lock_loop = loop
    return _mb_lock


# The last time a MusicBrainz request was made, for local rate-limiting
# when Redis is down.The slot is spent even if the request fails,
# so a retry has to wait
def _stamp_request_time() -> None:
    global _last_request_time
    _last_request_time = time.monotonic()


async def _mb_get(url: str, params: dict | None) -> httpx.Response:
    return await get_client(
        "musicbrainz",
        timeout=MB_TIMEOUT_S,
        follow_redirects=True,
    ).get(url, params=params)


async def _mb_get_locally_limited(
    url: str, params: dict | None
) -> httpx.Response:
    async with _get_mb_lock():
        elapsed = time.monotonic() - _last_request_time
        if elapsed < MB_MIN_INTERVAL_S:
            await asyncio.sleep(MB_MIN_INTERVAL_S - elapsed)
        try:
            return await _mb_get(url, params)
        finally:
            # A timed-out call still consumed its MB rate-limit slot,
            # so the retry has to wait out the full interval
            # rather than fire immediately
            _stamp_request_time()


# Waits for this call's turn, falling back to local limiting when Redis is down.
# Either path spends the slot even if the call fails, so a retry waits a fresh
# interval
async def _mb_get_limited(url: str, params: dict | None) -> httpx.Response:
    wait_s = await _mb_limiter.reserve()
    if wait_s is None:
        return await _mb_get_locally_limited(url, params)
    if wait_s > 0:
        await asyncio.sleep(wait_s)
    try:
        return await _mb_get(url, params)
    finally:
        _stamp_request_time()


# Rate-limited GET against MB, retrying once on 429/503 and on transient
# transport faults (read timeouts, dropped connections) with a short backoff
# on top of the routine inter-request spacing
async def mb_fetch(url: str, params: dict | None = None) -> httpx.Response:
    for attempt in range(MB_MAX_ATTEMPTS):
        is_last_attempt = attempt == MB_MAX_ATTEMPTS - 1
        try:
            res = await _mb_get_limited(url, params)
        except MB_RETRYABLE_EXCEPTIONS as exc:
            if is_last_attempt:
                raise
            # The caller logs the full trace if the final attempt fails
            # and a retry that succeeds is not noteworthy
            logger.warning("MB fetch failed (%s), retrying", type(exc).__name__)
            await asyncio.sleep(MB_RETRY_BACKOFF_S)
            continue

        if res.status_code in MB_RETRYABLE_STATUS_CODES and not is_last_attempt:
            await asyncio.sleep(MB_RETRY_BACKOFF_S)
            continue
        return res


async def resolve_artist_mbid(name: str) -> str:
    clean_name = name.replace('"', "")
    query = f'artist:"{clean_name}"'
    try:
        res = await mb_fetch(
            f"{MB_BASE}/artist",
            params={"query": query, "limit": 1, "fmt": "json"},
        )
        if not res.is_success:
            return ""
        data = res.json()
        artists = data.get("artists") or []
        if not artists:
            return ""
        top = artists[0]
        if top.get("score", 0) < 85:
            return ""
        return top.get("id", "")
    except Exception:
        return ""


_NOISE_RE = re.compile(
    r"\s*[\(\[]\s*(?:official\s+(?:music\s+)?video|lyrics?|hd|remaster(?:ed)?|"
    r"audio|live|explicit|clean|radio\s+edit)\s*[\)\]]",
    re.IGNORECASE,
)
_FEAT_RE = re.compile(r"\s+feat\.?\s+.*$", re.IGNORECASE)
_QUOTES_RE = re.compile(r'^(["\'])(.+)\1$')
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_MB_ESCAPE_RE = re.compile(r"([\(\)\[\]{}\^~*?:\\/+\-&|!])")
_BY_RE = re.compile(r"\s+by\s+", re.IGNORECASE)
_DASH_RE = re.compile(r"\s*[–—‒/:\\-]\s*")

# Exclude remixes, remasters, demos, edits, instrumentals, excerpts, commentaries
# and acoustic versionsfrom canonical studio recordings
_CANON_EXCLUDE = (
    "-recording:(remix remaster remastered demo edit instrumental"
    " excerpt commentary acoustic)"
)

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
        artist = q[m.end() :].strip()
        track = q[: m.start()].strip()
        if artist and track:
            return artist, track

    return None, q.strip()


def _build_field_query(artist: str | None, title: str) -> str:
    esc_title = _escape_mb(title)

    # If artis is present, search for recordings with the given title and artist name,
    # as well as the reverse (title as artist and artist as title) to catch misattributed tracks.
    # Also include canonical studio recordings and fuzzy matches on the title
    if artist:
        esc_artist = _escape_mb(artist)
        forward = f'recording:("{esc_title}") AND artistname:("{esc_artist}")'
        reversed_ = f'recording:("{esc_artist}") AND artistname:("{esc_title}")'
        title_fuzzy = " AND ".join(
            f"recording:{_escape_mb(w)}~" for w in title.split() if w
        )
        canonical = (
            f"((({forward}) OR ({reversed_}))"
            f" AND primarytype:album AND primarytype:single"
            f" AND {_CANON_EXCLUDE})^4"
        )
        core = (
            f"({forward}) OR ({reversed_}) OR ({canonical})"
            f" OR ({title_fuzzy} AND artistname:{esc_artist}~)"
        )
    # If no artist is present, search for recordings with the given title, fuzzy matches on the title,
    # and canonical studio recordings. Also include a branch that searches for the title as an artist
    else:
        words = title.split()
        phrase = f'recording:("{esc_title}")'
        fuzzy = " AND ".join(f"recording:{_escape_mb(w)}~" for w in words if w)
        canonical = (
            f"(({phrase}) AND primarytype:album AND primarytype:single"
            f" AND {_CANON_EXCLUDE})^4"
        )
        if len(words) == 1:
            esc_word = _escape_mb(words[0])
            artist_branch = (
                f'artistname:"{esc_word}" AND -recording:({esc_word}~)'
            )
            core = f"({phrase} OR {fuzzy} OR {canonical}) OR ({artist_branch})"
        else:
            core = f"{phrase} OR ({fuzzy}) OR ({canonical})"

    return f"({core}) AND {_FIXED_FILTERS}"


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
    q_artist, q_title = _parse_artist_track(_FEAT_RE.sub("", cleaned).strip())
    return await search_tracks_fields(q_title, q_artist)


# Resolve a canonical MBID for a track using the title and artist to search
async def search_tracks_fields(title: str, artist: str | None = None) -> list:
    q_title = _FEAT_RE.sub("", _clean(title)).strip() if title else ""
    q_artist = _FEAT_RE.sub("", _clean(artist)).strip() if artist else None
    if not q_title:
        return []

    lucene_query = _build_field_query(q_artist, q_title)
    logger.debug("MB search query: %s", lucene_query)

    try:
        res = await mb_fetch(
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

        # MB returns a recording's releases in arbitrary order, so take the
        # original album: earliest release whose release group carries no
        # secondary type (compilation, soundtrack, ...), albums before
        # singles.  Undated releases sort last
        releases = r.get("releases") or []
        first_release = min(
            releases,
            key=lambda rel: (
                bool((rel.get("release-group") or {}).get("secondary-types")),
                {"Album": 0, "EP": 1, "Single": 2}.get(
                    (rel.get("release-group") or {}).get("primary-type"), 3
                ),
                rel.get("date") or "9999",
            ),
            default=None,
        )
        release_type = (
            first_release.get("release-group", {}).get("primary-type")
            if first_release
            else None
        )
        album = first_release.get("title") if first_release else None
        release_mbid = first_release.get("id") if first_release else None
        raw_date = (
            r.get("first-release-date")
            or (first_release.get("date") if first_release else None)
            or ""
        )
        year = raw_date[:4] or None

        mb_score = int(r.get("score") or 0)
        blended = _blend_score(q_artist, q_title, title, artist_name, mb_score)

        results.append(
            {
                "mbid": mbid,
                "title": title,
                "artist": artist_name,
                "album": album,
                "release_mbid": release_mbid,
                "release_type": release_type,
                "year": year,
                "release_date": raw_date or None,
                "duration_ms": r.get("length"),
                "score": blended,
            }
        )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


# Recording-detail fields shared by every code path that resolves nothing
# (no MBID match, non-MusicBrainz source, or a resolution failure)
EMPTY_RECORDING = {
    "duration_ms": None,
    "album": None,
    "release_mbid": None,
    "release_date": None,
}


# Resolve a canonical recording for a track, using the title and artist to
# search if the given MBID is not valid or missing. This helps to handle
# cases where the MBID might be incorrect (e.g. from Last.fm). Also returns
# duration_ms and album/release info, since Last.fm's artist.getTopTracks
# doesn't provide any of that.
async def resolve_canonical_recording(
    mbid: str, title: str | None = None, artist: str | None = None
) -> dict:
    if title:
        try:
            results = await search_tracks_fields(title, artist)
        except Exception:
            results = []
        if results:
            top = results[0]
            return {
                "mbid": top["mbid"],
                "duration_ms": top["duration_ms"],
                "album": top["album"],
                "release_mbid": top["release_mbid"],
                "release_date": top["release_date"],
            }

    return {"mbid": mbid, **EMPTY_RECORDING}


async def resolve_canonical_mbid(
    mbid: str, title: str | None = None, artist: str | None = None
) -> str:
    resolved = await resolve_canonical_recording(mbid, title, artist)
    return resolved["mbid"]
