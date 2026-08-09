from types import SimpleNamespace

from .cached_clients import wrap_clients
from .pipeline import run_pipeline
from .tags import MOOD_TAGS
from .types import Seed, Track
from .utils import get_field


class Clients(SimpleNamespace):
    pass


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# Normalises a raw Last.fm artist.getTopTracks entry into the same recording
# shape ListenBrainz's top-recordings-for-artist returns so callers don't
# need to know which source produced it
def _lastfm_track_to_recording(track, fallback_artist_mbid):
    title = get_field(track, "name")
    if not title:
        return None
    artist_field = get_field(track, "artist") or {}
    return {
        "mbid": get_field(track, "mbid") or "",
        "title": title,
        "artist_mbid": get_field(artist_field, "mbid") or fallback_artist_mbid,
        "duration_ms": None,
        "listen_count": _to_int(get_field(track, "playcount")),
        "user_count": _to_int(get_field(track, "listeners")),
        "tags": [],
    }


# Creates a namespace with the actual client implementations for the pipeline to use
# This is the default for production, but tests can override it with a mock or stub implementation
def _make_real_clients():
    from clients import lastfm, listenbrainz, musicbrainz, streaming

    # Discovers artist tracks via Last.fm, not ListenBrainz's top-recordings-for-artist
    async def fetch_top_recordings_for_artist(
        artist_mbid, artist_name, limit, api_key
    ):
        tracks = await lastfm.fetch_artist_top_tracks(
            artist_name, limit, api_key
        )
        return [
            recording
            for t in tracks
            if (recording := _lastfm_track_to_recording(t, artist_mbid))
        ]

    return Clients(
        fetch_tag_artists=lastfm.fetch_tag_artists,
        fetch_track_tags=lastfm.fetch_track_tags,
        fetch_track_tags_only=lastfm.fetch_track_tags_only,
        fetch_top_recordings_for_artist=fetch_top_recordings_for_artist,
        # Resolved lazily per track, not for every candidate: Last.fm mbids are often stale
        resolve_recording_mbid=musicbrainz.resolve_canonical_recording,
        fetch_recording_tags=listenbrainz.fetch_recording_tags,
        fetch_artist_popularity=listenbrainz.fetch_artist_popularity,
        resolve_artist_mbid=musicbrainz.resolve_artist_mbid,
        get_streaming_links=streaming.get_streaming_links,
    )


# Builds one wrapped client namespace. Meant to be built once at process
# startup and passed in as `clients`, rather than rebuilt on every request
def build_clients() -> Clients:
    return wrap_clients(_make_real_clients())


async def get_recommendations(
    seeds: list,
    api_key: str,
    mood=None,
    novelty: float = 0,
    exclude_seed_artists: bool = True,
    clients: Clients | None = None,
) -> list:
    if clients is None:
        clients = build_clients()
    return await run_pipeline(
        seeds,
        api_key,
        mood,
        novelty,
        clients,
        exclude_seed_artists,
    )


# Resolves one recording's canonical MusicBrainz data on demand, for the lazy
# per-track endpoint. Shares cache entries with the pipeline's own resolution
async def resolve_recording(
    mbid: str, title: str, artist: str, clients: Clients | None = None
) -> dict:
    if clients is None:
        clients = build_clients()
    return await clients.resolve_recording_mbid(mbid, title, artist)


__all__ = [
    "get_recommendations",
    "resolve_recording",
    "build_clients",
    "MOOD_TAGS",
    "Seed",
    "Track",
]
