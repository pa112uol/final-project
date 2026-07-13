from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass
class StreamingLinks:
    apple_music: Optional[str]
    preview: Optional[str]
    youtube_video_id: Optional[str]
    spotify: str


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
            },
            "relevanceScore": self.relevance_score,
            "noveltyScore": self.novelty_score,
            "tags": self.tags,
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


@dataclass
class ScoredCandidate(Candidate):
    final_score: float = 0.0
    relevance_score: float = 0.0
    novelty_score: float = 0.0


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

    async def resolve_final_mbid(
        self, mbid: str, title: str, artist: str
    ) -> str: ...

    async def get_streaming_links(
        self, artist: str, title: str
    ) -> StreamingLinks: ...
