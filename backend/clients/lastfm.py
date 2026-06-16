import logging
import httpx
from .http import get_client

LASTFM_BASE = "https://ws.audioscrobbler.com/2.0"

logger = logging.getLogger(__name__)

_CLIENT = dict(
    timeout=10,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)


async def _lf_fetch(params: dict, api_key: str):
    all_params = dict(params)
    all_params["api_key"] = api_key
    all_params["format"] = "json"
    try:
        res = await get_client("lastfm", **_CLIENT).get(LASTFM_BASE, params=all_params)
        if not res.is_success:
            return None
        return res.json()
    except Exception:
        return None


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
    track_tags = _parse_tags(track_data.get("toptags", {}).get("tag") if track_data else None)
    if track_tags:
        return track_tags

    artist_data = await _lf_fetch(
        {"method": "artist.getTopTags", "artist": artist, "autocorrect": "1"},
        api_key,
    )
    return _parse_tags(
        artist_data.get("toptags", {}).get("tag") if artist_data else None
    )


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
    return _parse_tags(data.get("toptags", {}).get("tag") if data else None)


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
    raw = data.get("topartists", {}).get("artist") if data else None
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
    raw = data.get("toptracks", {}).get("track") if data else None
    if not raw:
        return []
    return raw if isinstance(raw, list) else [raw]
