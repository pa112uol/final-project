import sys
import os

# Allow importing clients from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .pipeline import run_pipeline
from .tags import MOOD_TAGS
from .types import Seed, Track


async def _make_real_clients():
    from clients.lastfm import (
        fetch_track_tags,
        fetch_track_tags_only,
        fetch_tag_artists,
    )
    from clients.listenbrainz import (
        fetch_artist_popularity,
        fetch_artist_top_recordings,
        fetch_recording_tags,
    )
    from clients.mb import resolve_artist_mbid
    from clients.streaming import get_streaming_links

    class RealClients:
        async def fetch_tag_artists(self, tag, page, limit, api_key):
            return await fetch_tag_artists(tag, page, limit, api_key)

        async def fetch_track_tags(self, title, artist, api_key, mbid=None):
            return await fetch_track_tags(title, artist, api_key, mbid)

        async def fetch_track_tags_only(
            self, title, artist, api_key, mbid=None
        ):
            return await fetch_track_tags_only(title, artist, api_key, mbid)

        async def fetch_artist_top_recordings(self, mbid, limit):
            return await fetch_artist_top_recordings(mbid, limit)

        async def resolve_artist_mbid(self, name):
            return await resolve_artist_mbid(name)

        async def fetch_recording_tags(self, mbid):
            return await fetch_recording_tags(mbid)

        async def fetch_artist_popularity(self, mbids):
            return await fetch_artist_popularity(mbids)

        async def get_streaming_links(self, artist, title):
            return await get_streaming_links(artist, title)

    return RealClients()


async def get_recommendations(
    seeds: list,
    api_key: str,
    mood=None,
    novelty: float = 0,
    exclude_seed_artists: bool = True,
) -> list:
    clients = await _make_real_clients()
    return await run_pipeline(
        seeds,
        api_key,
        mood,
        novelty,
        clients,
        exclude_seed_artists,
    )


__all__ = ["get_recommendations", "MOOD_TAGS", "Seed", "Track"]
