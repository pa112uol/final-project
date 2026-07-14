import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clients.streaming import (
    _force_https,
    _fetch_itunes_links,
    _fetch_youtube_video_id,
    get_streaming_links,
)
from recommendations.types import StreamingLinks


class TestForceHttps:
    def test_replaces_http_with_https(self):
        assert (
            _force_https("http://example.com/track")
            == "https://example.com/track"
        )

    def test_leaves_https_unchanged(self):
        assert (
            _force_https("https://example.com/track")
            == "https://example.com/track"
        )

    def test_returns_none_for_none_input(self):
        assert _force_https(None) is None

    def test_returns_none_for_empty_string(self):
        assert _force_https("") is None

    def test_only_replaces_first_http_occurrence(self):
        url = "http://example.com/http://nested"
        result = _force_https(url)
        assert result.startswith("https://")
        assert result.count("http://") == 1


class TestFetchItunesLinks:
    def make_resp(self, data, success=True):
        r = MagicMock()
        r.is_success = success
        r.json = lambda: data
        return r

    async def test_returns_apple_music_and_preview_urls(self):
        data = {
            "results": [
                {
                    "trackViewUrl": "http://music.apple.com/track/1",
                    "previewUrl": "http://audio-ssl.itunes.apple.com/preview.m4a",
                }
            ]
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp(data))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Radiohead", "Creep")
        assert result["apple_music"] == "https://music.apple.com/track/1"
        assert (
            result["preview"]
            == "https://audio-ssl.itunes.apple.com/preview.m4a"
        )

    async def test_forces_https_on_returned_urls(self):
        data = {
            "results": [
                {
                    "trackViewUrl": "http://music.apple.com/x",
                    "previewUrl": "http://preview.example.com/audio.m4a",
                }
            ]
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp(data))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Artist", "Song")
        assert result["apple_music"].startswith("https://")
        assert result["preview"].startswith("https://")

    async def test_returns_none_urls_when_results_empty(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp({"results": []}))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Artist", "Song")
        assert result == {"apple_music": None, "preview": None, "artwork": None}

    async def test_returns_none_urls_on_http_failure(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp({}, success=False))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Artist", "Song")
        assert result == {"apple_music": None, "preview": None, "artwork": None}

    async def test_returns_none_urls_on_exception(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("timeout"))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Artist", "Song")
        assert result == {"apple_music": None, "preview": None, "artwork": None}

    async def test_returns_artwork_in_three_sizes(self):
        data = {
            "results": [
                {
                    "trackViewUrl": "https://music.apple.com/x",
                    "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/abc/100x100bb.jpg",
                }
            ]
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp(data))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Artist", "Song")
        assert result["artwork"] == {
            "small": "https://is1-ssl.mzstatic.com/image/thumb/abc/100x100bb.jpg",
            "medium": "https://is1-ssl.mzstatic.com/image/thumb/abc/300x300bb.jpg",
            "large": "https://is1-ssl.mzstatic.com/image/thumb/abc/600x600bb.jpg",
        }

    async def test_artwork_none_when_field_absent(self):
        data = {"results": [{"trackViewUrl": "https://music.apple.com/x"}]}
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp(data))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Artist", "Song")
        assert result["artwork"] is None

    async def test_artwork_forces_https(self):
        data = {
            "results": [
                {
                    "artworkUrl100": "http://is1-ssl.mzstatic.com/image/thumb/abc/100x100bb.jpg",
                }
            ]
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp(data))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Artist", "Song")
        assert all(u.startswith("https://") for u in result["artwork"].values())

    async def test_returns_none_preview_when_key_absent(self):
        data = {"results": [{"trackViewUrl": "http://music.apple.com/x"}]}
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp(data))
        with patch("clients.streaming.get_client", return_value=client):
            result = await _fetch_itunes_links("Artist", "Song")
        assert result["preview"] is None
        assert result["apple_music"] is not None


class TestFetchYoutubeVideoId:
    async def test_returns_none_when_api_key_missing(self):
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
            result = await _fetch_youtube_video_id("Artist", "Song")
        assert result is None

    async def test_returns_video_id_on_success(self):
        data = {"items": [{"id": {"videoId": "abc123"}}]}
        client = MagicMock()
        client.get = AsyncMock(
            return_value=MagicMock(is_success=True, json=lambda: data)
        )
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            result = await _fetch_youtube_video_id("Artist", "Song")
        assert result == "abc123"

    async def test_returns_none_on_empty_items(self):
        data = {"items": []}
        client = MagicMock()
        client.get = AsyncMock(
            return_value=MagicMock(is_success=True, json=lambda: data)
        )
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            result = await _fetch_youtube_video_id("Artist", "Song")
        assert result is None

    async def test_returns_none_on_http_failure(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=MagicMock(is_success=False))
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            result = await _fetch_youtube_video_id("Artist", "Song")
        assert result is None

    async def test_returns_none_on_exception(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("network error"))
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            result = await _fetch_youtube_video_id("Artist", "Song")
        assert result is None


class TestGetStreamingLinks:
    async def test_returns_streaming_links_dataclass(self):
        artwork = {
            "small": "https://a/100x100bb.jpg",
            "medium": "https://a/300x300bb.jpg",
            "large": "https://a/600x600bb.jpg",
        }
        itunes = {
            "apple_music": "https://music.apple.com/x",
            "preview": None,
            "artwork": artwork,
        }
        with patch(
            "clients.streaming._fetch_itunes_links",
            new=AsyncMock(return_value=itunes),
        ), patch(
            "clients.streaming._fetch_youtube_video_id",
            new=AsyncMock(return_value="yt123"),
        ):
            result = await get_streaming_links("Artist", "Song")
        assert isinstance(result, StreamingLinks)
        assert result.apple_music == "https://music.apple.com/x"
        assert result.youtube_video_id == "yt123"
        assert result.artwork == artwork

    async def test_spotify_url_contains_encoded_query(self):
        itunes = {"apple_music": None, "preview": None}
        with patch(
            "clients.streaming._fetch_itunes_links",
            new=AsyncMock(return_value=itunes),
        ), patch(
            "clients.streaming._fetch_youtube_video_id",
            new=AsyncMock(return_value=None),
        ):
            result = await get_streaming_links("Artist", "Song Title")
        assert result.spotify.startswith("https://open.spotify.com/search/")
        assert " " not in result.spotify

    async def test_spotify_url_always_set_regardless_of_other_failures(self):
        itunes = {"apple_music": None, "preview": None}
        with patch(
            "clients.streaming._fetch_itunes_links",
            new=AsyncMock(return_value=itunes),
        ), patch(
            "clients.streaming._fetch_youtube_video_id",
            new=AsyncMock(return_value=None),
        ):
            result = await get_streaming_links("X", "Y")
        assert result.spotify is not None
        assert "open.spotify.com" in result.spotify
