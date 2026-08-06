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


ITUNES_EMPTY = {"apple_music": None, "preview": None, "artwork": None}


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
            result, _ = await _fetch_itunes_links("Radiohead", "Creep")
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
            result, _ = await _fetch_itunes_links("Artist", "Song")
        assert result["apple_music"].startswith("https://")
        assert result["preview"].startswith("https://")

    async def test_returns_none_urls_when_results_empty(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp({"results": []}))
        with patch("clients.streaming.get_client", return_value=client):
            result, _ = await _fetch_itunes_links("Artist", "Song")
        assert result == ITUNES_EMPTY

    async def test_returns_none_urls_on_http_failure(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp({}, success=False))
        with patch("clients.streaming.get_client", return_value=client):
            result, _ = await _fetch_itunes_links("Artist", "Song")
        assert result == ITUNES_EMPTY

    async def test_returns_none_urls_on_exception(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("timeout"))
        with patch("clients.streaming.get_client", return_value=client):
            result, _ = await _fetch_itunes_links("Artist", "Song")
        assert result == ITUNES_EMPTY

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
            result, _ = await _fetch_itunes_links("Artist", "Song")
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
            result, _ = await _fetch_itunes_links("Artist", "Song")
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
            result, _ = await _fetch_itunes_links("Artist", "Song")
        assert all(u.startswith("https://") for u in result["artwork"].values())

    async def test_returns_none_preview_when_key_absent(self):
        data = {"results": [{"trackViewUrl": "http://music.apple.com/x"}]}
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp(data))
        with patch("clients.streaming.get_client", return_value=client):
            result, _ = await _fetch_itunes_links("Artist", "Song")
        assert result["preview"] is None
        assert result["apple_music"] is not None

    async def test_an_empty_result_counts_as_completed(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp({"results": []}))
        with patch("clients.streaming.get_client", return_value=client):
            _, completed = await _fetch_itunes_links("Artist", "Song")
        assert completed is True

    async def test_a_found_result_counts_as_completed(self):
        data = {"results": [{"trackViewUrl": "https://music.apple.com/x"}]}
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp(data))
        with patch("clients.streaming.get_client", return_value=client):
            _, completed = await _fetch_itunes_links("Artist", "Song")
        assert completed is True

    async def test_an_http_failure_does_not_count_as_completed(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=self.make_resp({}, success=False))
        with patch("clients.streaming.get_client", return_value=client):
            _, completed = await _fetch_itunes_links("Artist", "Song")
        assert completed is False

    async def test_an_exception_does_not_count_as_completed(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("timeout"))
        with patch("clients.streaming.get_client", return_value=client):
            _, completed = await _fetch_itunes_links("Artist", "Song")
        assert completed is False


class TestFetchYoutubeVideoId:
    async def test_returns_none_when_api_key_missing(self):
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
            result, _ = await _fetch_youtube_video_id("Artist", "Song")
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
            result, _ = await _fetch_youtube_video_id("Artist", "Song")
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
            result, _ = await _fetch_youtube_video_id("Artist", "Song")
        assert result is None

    async def test_returns_none_on_http_failure(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=MagicMock(is_success=False))
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            result, _ = await _fetch_youtube_video_id("Artist", "Song")
        assert result is None

    async def test_returns_none_on_exception(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("network error"))
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            result, _ = await _fetch_youtube_video_id("Artist", "Song")
        assert result is None

    async def test_an_http_failure_does_not_count_as_completed(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=MagicMock(is_success=False))
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            _, completed = await _fetch_youtube_video_id("Artist", "Song")
        assert completed is False

    async def test_an_exception_does_not_count_as_completed(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("network error"))
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            _, completed = await _fetch_youtube_video_id("Artist", "Song")
        assert completed is False

    async def test_no_matching_video_counts_as_completed(self):
        client = MagicMock()
        client.get = AsyncMock(
            return_value=MagicMock(is_success=True, json=lambda: {"items": []})
        )
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"}), patch(
            "clients.streaming.get_client", return_value=client
        ):
            _, completed = await _fetch_youtube_video_id("Artist", "Song")
        assert completed is True

    # A deliberate configuration, not a transient fault, so it must not shorten
    # the cache lifetime of the iTunes half of the result.
    async def test_a_missing_api_key_counts_as_completed(self):
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
            _, completed = await _fetch_youtube_video_id("Artist", "Song")
        assert completed is True


class TestGetStreamingLinks:
    @staticmethod
    def _patched(itunes, itunes_ok, video_id, youtube_ok):
        return (
            patch(
                "clients.streaming._fetch_itunes_links",
                new=AsyncMock(return_value=(itunes, itunes_ok)),
            ),
            patch(
                "clients.streaming._fetch_youtube_video_id",
                new=AsyncMock(return_value=(video_id, youtube_ok)),
            ),
        )

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
        itunes_patch, youtube_patch = self._patched(itunes, True, "yt123", True)
        with itunes_patch, youtube_patch:
            result = await get_streaming_links("Artist", "Song")
        assert isinstance(result, StreamingLinks)
        assert result.apple_music == "https://music.apple.com/x"
        assert result.youtube_video_id == "yt123"
        assert result.artwork == artwork

    async def test_spotify_url_contains_encoded_query(self):
        itunes_patch, youtube_patch = self._patched(
            ITUNES_EMPTY, True, None, True
        )
        with itunes_patch, youtube_patch:
            result = await get_streaming_links("Artist", "Song Title")
        assert result.spotify.startswith("https://open.spotify.com/search/")
        assert " " not in result.spotify

    async def test_spotify_url_always_set_regardless_of_other_failures(self):
        itunes_patch, youtube_patch = self._patched(
            ITUNES_EMPTY, False, None, False
        )
        with itunes_patch, youtube_patch:
            result = await get_streaming_links("X", "Y")
        assert result.spotify is not None
        assert "open.spotify.com" in result.spotify

    async def test_both_lookups_completing_reports_no_failure(self):
        itunes_patch, youtube_patch = self._patched(
            ITUNES_EMPTY, True, None, True
        )
        with itunes_patch, youtube_patch:
            result = await get_streaming_links("Artist", "Song")
        assert result.lookup_failed is False

    @pytest.mark.parametrize(
        "itunes_ok,youtube_ok", [(True, False), (False, True), (False, False)]
    )
    async def test_either_lookup_failing_reports_a_failure(
        self, itunes_ok, youtube_ok
    ):
        itunes_patch, youtube_patch = self._patched(
            ITUNES_EMPTY, itunes_ok, None, youtube_ok
        )
        with itunes_patch, youtube_patch:
            result = await get_streaming_links("Artist", "Song")
        assert result.lookup_failed is True
