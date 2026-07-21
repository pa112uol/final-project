import sys
import os
from types import SimpleNamespace

# Allow importing clients from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .pipeline import run_pipeline
from .tags import MOOD_TAGS
from .types import Seed, Track
from .utils import get_field


class Clients(SimpleNamespace):
    pass


# RECORDING_SOURCE env var controls which source fetch_top_recordings_for_artist
# uses for track discovery: "listenbrainz" (default) or "lastfm"
RECORDING_SOURCES = ("listenbrainz", "lastfm")


def _recording_source():
    value = os.environ.get("RECORDING_SOURCE", "listenbrainz").strip().lower()
    return value if value in RECORDING_SOURCES else "listenbrainz"


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

    async def fetch_top_recordings_for_artist(
        artist_mbid, artist_name, limit, api_key
    ):
        if _recording_source() == "lastfm":
            tracks = await lastfm.fetch_artist_top_tracks(
                artist_name, limit, api_key
            )
            return [
                recording
                for t in tracks
                if (recording := _lastfm_track_to_recording(t, artist_mbid))
            ]
        return await listenbrainz.fetch_artist_top_recordings(
            artist_mbid, limit
        )

    # Last.fm's track mbids are frequently stale or missing entirely. Rather
    # than resolving every candidate up front (hundreds of MusicBrainz calls
    # per request, which gets us rate-limited), this only runs for the
    # handful of tracks that actually make it into the final results.
    async def resolve_recording_mbid(mbid, title, artist):
        if _recording_source() != "lastfm":
            return {
                "mbid": mbid,
                "duration_ms": None,
                "album": None,
                "release_mbid": None,
                "release_date": None,
            }
        return await musicbrainz.resolve_canonical_recording(mbid, title, artist)

    return Clients(
        fetch_tag_artists=lastfm.fetch_tag_artists,
        fetch_track_tags=lastfm.fetch_track_tags,
        fetch_track_tags_only=lastfm.fetch_track_tags_only,
        fetch_top_recordings_for_artist=fetch_top_recordings_for_artist,
        resolve_recording_mbid=resolve_recording_mbid,
        fetch_recording_tags=listenbrainz.fetch_recording_tags,
        fetch_artist_popularity=listenbrainz.fetch_artist_popularity,
        resolve_artist_mbid=musicbrainz.resolve_artist_mbid,
        get_streaming_links=streaming.get_streaming_links,
    )


async def get_recommendations(
    seeds: list,
    api_key: str,
    mood=None,
    novelty: float = 0,
    exclude_seed_artists: bool = True,
) -> list:
    clients = _make_real_clients()
    return await run_pipeline(
        seeds,
        api_key,
        mood,
        novelty,
        clients,
        exclude_seed_artists,
    )


__all__ = ["get_recommendations", "MOOD_TAGS", "Seed", "Track"]
