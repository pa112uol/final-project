# Read-through Redis cache over the pipeline's external clients

import logging
from types import SimpleNamespace

from clients.http import UpstreamError

from caching.async_cache import get_async_cache
from caching.config import (
    NEGATIVE_TTL_S,
    TTL_ARTIST_MBID,
    TTL_ARTIST_POPULARITY,
    TTL_RECORDING_MBID,
    TTL_RECORDING_TAGS,
    TTL_STREAMING_LINKS,
    TTL_TAG_ARTISTS,
    TTL_TOP_RECORDINGS,
    TTL_TRACK_TAGS,
)
from caching.keys import build_key

from .types import StreamingLinks

logger = logging.getLogger(__name__)

NS_TAG_ARTISTS = "lf:tagartists"
NS_TRACK_TAGS = "lf:tracktags"
NS_TRACK_TAGS_ONLY = "lf:tracktagsonly"
NS_RECORDING_TAGS = "lb:rectags"
NS_TOP_RECORDINGS = "lb:toprecordings"
NS_ARTIST_POPULARITY = "lb:artistpop"
NS_ARTIST_MBID = "mb:artist"
NS_RECORDING_MBID = "mb:recording"
NS_STREAMING = "stream:links"

# Cached values are wrapped in a one-key envelope
_ENVELOPE_FIELD = "v"


def _wrap(value: object) -> dict:
    return {_ENVELOPE_FIELD: value}


# Unwraps a stored envelope, returning the miss sentinel for anything that does
# not look like one
_MISS = object()


def _unwrap(entry: object) -> object:
    if isinstance(entry, dict) and _ENVELOPE_FIELD in entry:
        return entry[_ENVELOPE_FIELD]
    return _MISS


# Runs the read-through: cached value if present, otherwise the real client.
# A transient UpstreamError is never cached. Callers may receive the default
# or request the original signal when the pipeline has its own retry policy.
async def _read_through(
    namespace: str,
    key_parts: list,
    ttl: int,
    fetch,
    is_positive=bool,
    default=None,
    reraise_upstream: bool = False,
):
    cache = get_async_cache()
    key = build_key(namespace, *key_parts)
    cached = _unwrap(await cache.get_json(key))
    if cached is not _MISS:
        return cached
    try:
        value = await fetch()
    except UpstreamError as exc:
        logger.warning("[cache] upstream fetch failed for %s: %s", key, exc)
        if reraise_upstream:
            raise
        return default
    stored_ttl = ttl if is_positive(value) else NEGATIVE_TTL_S
    await cache.set_json(key, _wrap(value), stored_ttl)
    return value


def _cached_fetch_tag_artists(inner):
    async def fetch_tag_artists(tag, page, limit, api_key):
        return await _read_through(
            NS_TAG_ARTISTS,
            [tag, page, limit],
            TTL_TAG_ARTISTS,
            lambda: inner(tag, page, limit, api_key),
            default=[],
        )

    return fetch_tag_artists


def _cached_fetch_track_tags(inner):
    async def fetch_track_tags(title, artist, api_key, mbid=None):
        return await _read_through(
            NS_TRACK_TAGS,
            [title, artist, mbid],
            TTL_TRACK_TAGS,
            lambda: inner(title, artist, api_key, mbid),
            default=[],
        )

    return fetch_track_tags


def _cached_fetch_track_tags_only(inner):
    async def fetch_track_tags_only(title, artist, api_key, mbid=None):
        return await _read_through(
            NS_TRACK_TAGS_ONLY,
            [title, artist, mbid],
            TTL_TRACK_TAGS,
            lambda: inner(title, artist, api_key, mbid),
            default=[],
            # The pipeline catches this signal and leaves the candidate
            # eligible for its post-selection retry. Returning [] here would
            # make a transient failure indistinguishable from a healthy empty
            # response and incorrectly mark the candidate as enriched.
            reraise_upstream=True,
        )

    return fetch_track_tags_only


def _cached_fetch_recording_tags(inner):
    async def fetch_recording_tags(mbid):
        return await _read_through(
            NS_RECORDING_TAGS,
            [mbid],
            TTL_RECORDING_TAGS,
            lambda: inner(mbid),
            default=[],
        )

    return fetch_recording_tags


def _cached_fetch_top_recordings_for_artist(inner):
    async def fetch_top_recordings_for_artist(
        artist_mbid, artist_name, limit, api_key
    ):
        return await _read_through(
            NS_TOP_RECORDINGS,
            [artist_mbid, artist_name, limit],
            TTL_TOP_RECORDINGS,
            lambda: inner(artist_mbid, artist_name, limit, api_key),
            default=[],
        )

    return fetch_top_recordings_for_artist


def _cached_resolve_artist_mbid(inner):
    async def resolve_artist_mbid(name):
        return await _read_through(
            NS_ARTIST_MBID,
            [name],
            TTL_ARTIST_MBID,
            lambda: inner(name),
        )

    return resolve_artist_mbid


_RECORDING_RESOLVED_FIELDS = (
    "duration_ms",
    "album",
    "release_mbid",
    "release_date",
)


def _recording_was_resolved(value: object) -> bool:
    if not isinstance(value, dict):
        return bool(value)
    return any(
        value.get(field) is not None for field in _RECORDING_RESOLVED_FIELDS
    )


def _cached_resolve_recording_mbid(inner):
    async def resolve_recording_mbid(mbid, title, artist):
        return await _read_through(
            NS_RECORDING_MBID,
            [mbid, title, artist],
            TTL_RECORDING_MBID,
            lambda: inner(mbid, title, artist),
            is_positive=_recording_was_resolved,
        )

    return resolve_recording_mbid


# The only client returning a dataclass rather than JSON-native data
def _streaming_to_dict(links: StreamingLinks) -> dict:
    return {
        "apple_music": links.apple_music,
        "preview": links.preview,
        "youtube_video_id": links.youtube_video_id,
        "spotify": links.spotify,
        "artwork": links.artwork,
    }


def _streaming_from_dict(data: dict) -> StreamingLinks:
    return StreamingLinks(
        apple_music=data.get("apple_music"),
        preview=data.get("preview"),
        youtube_video_id=data.get("youtube_video_id"),
        spotify=data.get("spotify", ""),
        artwork=data.get("artwork"),
    )


# Cached per (artist, title) pair rather than per batch
def _cached_get_streaming_links(inner):
    async def get_streaming_links(artist, title):
        cache = get_async_cache()
        key = build_key(NS_STREAMING, artist, title)
        cached = _unwrap(await cache.get_json(key))
        if cached is not _MISS and isinstance(cached, dict):
            return _streaming_from_dict(cached)
        links = await inner(artist, title)
        ttl = (
            NEGATIVE_TTL_S
            if getattr(links, "lookup_failed", False)
            else TTL_STREAMING_LINKS
        )
        await cache.set_json(key, _wrap(_streaming_to_dict(links)), ttl)
        return links

    return get_streaming_links


# Cached per MBID rather than per batch. The pipeline passes
# list(set(artist_mbids)), so the batch differs between runs in both membership
# and ordering and a whole-batch key would essentially never hit, while the
# individual artists inside it repeat constantly
def _cached_fetch_artist_popularity(inner):
    async def fetch_artist_popularity(artist_mbids):
        cache = get_async_cache()
        valid = [m for m in artist_mbids if m]

        if not valid:
            return {}

        keys = {mbid: build_key(NS_ARTIST_POPULARITY, mbid) for mbid in valid}
        stored = await cache.get_many_json(list(keys.values()))

        result = {}
        missing = []
        for mbid, key in keys.items():
            value = _unwrap(stored.get(key, _MISS))
            if value is _MISS:
                missing.append(mbid)
            elif value is not None:
                result[mbid] = value

        if not missing:
            return result

        fetched = await inner(missing)
        # An MBID the upstream had no data for is cached as null so the next run
        # does not reask for it, but only for the short negative TTL in case the
        # gap was an outage rather than missing data
        await cache.set_many_json(
            {
                keys[mbid]: (
                    _wrap(fetched.get(mbid)),
                    (
                        TTL_ARTIST_POPULARITY
                        if mbid in fetched
                        else NEGATIVE_TTL_S
                    ),
                )
                for mbid in missing
            }
        )
        result.update(fetched)
        return result

    return fetch_artist_popularity


_WRAPPERS = {
    "fetch_tag_artists": _cached_fetch_tag_artists,
    "fetch_track_tags": _cached_fetch_track_tags,
    "fetch_track_tags_only": _cached_fetch_track_tags_only,
    "fetch_recording_tags": _cached_fetch_recording_tags,
    "fetch_top_recordings_for_artist": _cached_fetch_top_recordings_for_artist,
    "resolve_artist_mbid": _cached_resolve_artist_mbid,
    "resolve_recording_mbid": _cached_resolve_recording_mbid,
    "get_streaming_links": _cached_get_streaming_links,
    "fetch_artist_popularity": _cached_fetch_artist_popularity,
}


# Returns a namespace exposing the same attributes with every known method
# read-through cached
def wrap_clients(clients):
    attributes = {
        name: getattr(clients, name)
        for name in dir(clients)
        if not name.startswith("_")
    }
    for name, decorate in _WRAPPERS.items():
        inner = attributes.get(name)
        if inner is None:
            logger.warning(
                "[cache] clients namespace has no %s, leaving uncached", name
            )
            continue
        attributes[name] = decorate(inner)
    return SimpleNamespace(**attributes)
