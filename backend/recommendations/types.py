from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable
from urllib.parse import quote

from .constants import SELECTION_TOP_MATCH


@dataclass
class StreamingLinks:
    apple_music: Optional[str]
    preview: Optional[str]
    youtube_video_id: Optional[str]
    spotify: str
    # {"small": url, "medium": url, "large": url} (100/300/600px) or None
    artwork: Optional[dict] = None
    # Whether the MusicBrainz lookup for this track failed
    lookup_failed: bool = False


def spotify_search_url(artist: str, title: str) -> str:
    return f"https://open.spotify.com/search/{quote(f'{artist} {title}')}"


# Streaming links without any upstream lookup
def search_only_streaming_links(artist: str, title: str) -> StreamingLinks:
    return StreamingLinks(
        apple_music=None,
        preview=None,
        youtube_video_id=None,
        spotify=spotify_search_url(artist, title),
        artwork=None,
        lookup_failed=False,
    )


@dataclass
class Seed:
    mbid: str
    title: str
    artist: str


@dataclass
class Release:
    mbid: str
    title: str
    date: Optional[str] = None


def _release_to_dict(r):
    if isinstance(r, Release):
        return {"mbid": r.mbid, "title": r.title, "date": r.date}
    return r


# The single element release list a resolved recording dict produces, used
# by resolved_to_dict for the lazy per-track endpoint's response shape
def releases_from_resolved(resolved: dict) -> list:
    if not resolved.get("album"):
        return []
    return [
        Release(
            mbid=resolved.get("release_mbid"),
            title=resolved["album"],
            date=resolved.get("release_date"),
        )
    ]


# camelCase view of the Track fields recording resolution supplies, matching
# Track.to_dict so a client can merge the patch field for field
def resolved_to_dict(resolved: dict) -> dict:
    return {
        "mbid": resolved.get("mbid"),
        "durationMs": resolved.get("duration_ms"),
        "firstReleaseDate": resolved.get("release_date"),
        "releases": [
            _release_to_dict(r) for r in releases_from_resolved(resolved)
        ],
    }


@dataclass
class Track:
    mbid: str
    title: str
    artist: str
    artist_mbid: str
    duration_ms: Optional[int]
    first_release_date: Optional[str]
    releases: list
    streaming: StreamingLinks
    relevance_score: float
    novelty_score: float
    tags: list = field(default_factory=list)
    selection_reason: str = SELECTION_TOP_MATCH

    def to_dict(self):
        return {
            "mbid": self.mbid,
            "title": self.title,
            "artist": self.artist,
            "artistMbid": self.artist_mbid,
            "durationMs": self.duration_ms,
            "firstReleaseDate": self.first_release_date,
            "releases": [_release_to_dict(r) for r in self.releases],
            "streaming": {
                "appleMusic": self.streaming.apple_music,
                "preview": self.streaming.preview,
                "youtubeVideoId": self.streaming.youtube_video_id,
                "spotify": self.streaming.spotify,
                "artwork": self.streaming.artwork,
            },
            "relevanceScore": self.relevance_score,
            "noveltyScore": self.novelty_score,
            "tags": self.tags,
            "selectionReason": self.selection_reason,
        }


@dataclass
class LFTag:
    name: str
    count: int


@dataclass
class LFArtist:
    name: str
    mbid: Optional[str] = None


@dataclass
class LBRecording:
    mbid: str
    title: str
    artist_mbid: str
    duration_ms: Optional[int]
    listen_count: int
    user_count: int
    tags: list


@dataclass
class Candidate:
    title: str
    artist: str
    artist_mbid: str
    mbid: str
    duration_ms: Optional[int]
    tag_weight_sum: float
    track_tag_score: float
    listen_count: int
    user_count: int
    artist_listen_count: int
    tags: list
    # How strongly the track expresses the requested mood, in [-1, 1]. Stays
    # 0.0 when no mood was requested, which zeroes the mood term in scoring
    mood_score: float = 0.0
    # Set once Last.fm track tags have been fetched, so the post-selection
    # top-up can skip anything the pre-selection pass already covered
    lf_enriched: bool = False


@dataclass
class ScoredCandidate(Candidate):
    final_score: float = 0.0
    relevance_score: float = 0.0
    novelty_score: float = 0.0
    # Set by MMR at pick time. Defaults to the top-match case so a candidate
    # that never went through selection reads as ranked on score alone
    # rather than claiming a diversity boost
    selection_reason: str = SELECTION_TOP_MATCH


@runtime_checkable
class PipelineClients(Protocol):
    async def fetch_tag_artists(
        self, tag: str, page: int, limit: int, api_key: str
    ) -> list: ...

    async def fetch_top_recordings_for_artist(
        self, mbid: str, name: str, limit: int, api_key: str
    ) -> list: ...

    async def resolve_artist_mbid(self, name: str) -> str: ...

    async def fetch_recording_tags(self, mbid: str) -> list: ...

    async def fetch_track_tags(
        self, title: str, artist: str, api_key: str, mbid: Optional[str] = None
    ) -> list: ...

    async def fetch_track_tags_only(
        self, title: str, artist: str, api_key: str, mbid: Optional[str] = None
    ) -> list: ...

    async def fetch_artist_popularity(self, mbids: list) -> dict: ...

    async def resolve_recording_mbid(
        self, mbid: str, title: str, artist: str
    ) -> dict: ...

    async def get_streaming_links(
        self, artist: str, title: str
    ) -> StreamingLinks: ...
