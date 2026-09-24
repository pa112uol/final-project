import logging
import re
import httpx
from .http import UpstreamError, get_client

LASTFM_BASE = "https://ws.audioscrobbler.com/2.0"

logger = logging.getLogger(__name__)

# Last.fm reports an unknown track or artist as error 6 with a "not found"
# message. That is an answer, not an outage, so it reads as an empty result
LASTFM_INVALID_PARAMETERS_ERROR = 6
# Covers both "Track not found" and "The artist you supplied could not be found"
_NOT_FOUND_PATTERN = re.compile(r"\bnot (be )?found\b", re.IGNORECASE)

# A single recommendations request fans out dozens of Last.fm calls; under
# FastAPI's real request concurrency the old max_connections=20 became the
# throughput ceiling rather than any upstream limit
_CLIENT = dict(
    timeout=10,
    limits=httpx.Limits(max_connections=60, max_keepalive_connections=30),
)


def _is_not_found(data: dict) -> bool:
    message = str(data.get("message", ""))
    return data.get("error") == LASTFM_INVALID_PARAMETERS_ERROR and bool(
        _NOT_FOUND_PATTERN.search(message)
    )


# Raises UpstreamError on failure rather than returning None, so a transient
# outage is never mistaken for a genuine empty result by the read-through cache.
# A "not found" answer returns an empty dict, which callers read as no data
async def _lf_fetch(params: dict, api_key: str) -> dict:
    all_params = dict(params)
    all_params["api_key"] = api_key
    all_params["format"] = "json"
    try:
        res = await get_client("lastfm", **_CLIENT).get(LASTFM_BASE, params=all_params)
    except httpx.HTTPError as exc:
        raise UpstreamError(f"Last.fm request failed: {exc}") from exc
    if not res.is_success:
        raise UpstreamError(f"Last.fm returned HTTP {res.status_code}")
    try:
        data = res.json()
    except ValueError as exc:
        raise UpstreamError(f"Last.fm returned invalid JSON: {exc}") from exc
    if isinstance(data, dict) and _is_not_found(data):
        return {}
    if isinstance(data, dict) and data.get("error") is not None:
        raise UpstreamError(
            f"Last.fm API error {data.get('error')}: {data.get('message', '')}"
        )
    return data


def _parse_tags(raw) -> list:
    if not raw:
        return []
    arr = raw if isinstance(raw, list) else [raw]
    result = []
    for t in arr:
        name = t.get("name", "") if isinstance(t, dict) else ""
        count_raw = t.get("count", 0) if isinstance(t, dict) else 0
        name = name.lower().strip()
        try:
            count = int(count_raw)
        except (TypeError, ValueError):
            count = 0
        if name:
            result.append({"name": name, "count": count})
    return result


# Top tags for a track, falling back to the artist's tags when Last.fm has none
# for the track (common for deep cuts). Used for both seed profiling and scoring
# candidate relevance at the track level.
async def fetch_track_tags(
    title: str, artist: str, api_key: str, mbid: str = None
) -> list:
    params = {
        "method": "track.getTopTags",
        "track": title,
        "artist": artist,
        "autocorrect": "1",
    }
    if mbid:
        params["mbid"] = mbid

    track_data = await _lf_fetch(params, api_key)
    track_tags = _parse_tags(track_data.get("toptags", {}).get("tag"))
    if track_tags:
        return track_tags

    artist_data = await _lf_fetch(
        {"method": "artist.getTopTags", "artist": artist, "autocorrect": "1"},
        api_key,
    )
    return _parse_tags(artist_data.get("toptags", {}).get("tag"))


async def fetch_track_tags_only(
    title: str, artist: str, api_key: str, mbid: str = None
) -> list:
    params = {
        "method": "track.getTopTags",
        "track": title,
        "artist": artist,
        "autocorrect": "1",
    }
    if mbid:
        params["mbid"] = mbid
    data = await _lf_fetch(params, api_key)
    return _parse_tags(data.get("toptags", {}).get("tag"))


async def fetch_tag_artists(
    tag: str, page: int, limit: int, api_key: str
) -> list:
    data = await _lf_fetch(
        {
            "method": "tag.getTopArtists",
            "tag": tag,
            "limit": str(limit),
            "page": str(page),
        },
        api_key,
    )
    raw = data.get("topartists", {}).get("artist")
    if not raw:
        return []
    arr = raw if isinstance(raw, list) else [raw]
    result = []
    for a in arr:
        name = a.get("name", "") if isinstance(a, dict) else ""
        mbid = a.get("mbid") if isinstance(a, dict) else None
        if name:
            result.append({"name": name, "mbid": mbid})
    return result


async def search_track(
    query: str, api_key: str, limit: int = 10
) -> list:
    data = await _lf_fetch(
        {"method": "track.search", "track": query, "limit": str(limit)},
        api_key,
    )
    raw = data.get("results", {}).get("trackmatches", {}).get("track")
    if not raw:
        return []
    arr = raw if isinstance(raw, list) else [raw]
    return [
        {
            "name": t.get("name", ""),
            "artist": t.get("artist", ""),
            "url": t.get("url", ""),
            "listeners": t.get("listeners", ""),
            "mbid": t.get("mbid") or None,
        }
        for t in arr
    ]


async def fetch_artist_top_tracks(
    artist: str, limit: int, api_key: str
) -> list:
    data = await _lf_fetch(
        {
            "method": "artist.getTopTracks",
            "artist": artist,
            "limit": str(limit),
            "autocorrect": "1",
        },
        api_key,
    )
    raw = data.get("toptracks", {}).get("track")
    if not raw:
        return []
    return raw if isinstance(raw, list) else [raw]
