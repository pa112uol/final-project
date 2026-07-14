import asyncio
import os
import logging
import urllib.parse
import httpx
from .http import get_client

ITUNES_BASE = "https://itunes.apple.com/search"
YOUTUBE_SEARCH_BASE = "https://www.googleapis.com/youtube/v3/search"

logger = logging.getLogger(__name__)

_CLIENT = dict(
    timeout=10,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)

_ARTWORK_SIZES = {"small": 100, "medium": 300, "large": 600}


def _force_https(url: str = None) -> str:
    if not url:
        return None
    return url.replace("http://", "https://", 1)


def _artwork_urls(url: str = None) -> dict | None:
    url = _force_https(url)
    if not url:
        return None
    return {
        name: url.replace("100x100bb", f"{px}x{px}bb")
        for name, px in _ARTWORK_SIZES.items()
    }


_ITUNES_EMPTY = {"apple_music": None, "preview": None, "artwork": None}


async def _fetch_itunes_links(artist: str, title: str) -> dict:
    try:
        res = await get_client("streaming", **_CLIENT).get(
            ITUNES_BASE,
            params={
                "term": f"{artist} {title}",
                "entity": "song",
                "limit": "1",
            },
        )
        if not res.is_success:
            return dict(_ITUNES_EMPTY)
        data = res.json()
        item = (data.get("results") or [None])[0]
        if not item:
            return dict(_ITUNES_EMPTY)
        return {
            "apple_music": _force_https(item.get("trackViewUrl")),
            "preview": _force_https(item.get("previewUrl")),
            "artwork": _artwork_urls(item.get("artworkUrl100")),
        }
    except Exception:
        return dict(_ITUNES_EMPTY)


async def _fetch_youtube_video_id(artist: str, title: str) -> str:
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return None
    try:
        res = await get_client("streaming", **_CLIENT).get(
            YOUTUBE_SEARCH_BASE,
            params={
                "part": "snippet",
                "q": f'"{artist}" "{title}"',
                "type": "video",
                "videoCategoryId": "10",
                "maxResults": "1",
                "key": api_key,
            },
        )
        if not res.is_success:
            return None
        data = res.json()
        items = data.get("items") or []
        if not items:
            return None
        return (items[0].get("id") or {}).get("videoId")
    except Exception:
        return None


async def get_streaming_links(artist: str, title: str):
    from recommendations.types import StreamingLinks

    query = urllib.parse.quote(f"{artist} {title}")
    itunes, youtube_video_id = await asyncio.gather(
        _fetch_itunes_links(artist, title),
        _fetch_youtube_video_id(artist, title),
    )
    return StreamingLinks(
        apple_music=itunes["apple_music"],
        preview=itunes["preview"],
        youtube_video_id=youtube_video_id,
        spotify=f"https://open.spotify.com/search/{query}",
        artwork=itunes.get("artwork"),
    )
