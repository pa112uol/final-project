import asyncio
import json
import threading
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from django.test import RequestFactory
from django.urls import resolve
import api.views as views
from api.views import random_tracks


@pytest.fixture
def rf():
    return RequestFactory()


def _mb_success(recordings):
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {"recordings": recordings}
    return resp


def _mb_error(status_code=503):
    resp = MagicMock()
    resp.is_success = False
    resp.status_code = status_code
    return resp


def _recording(
    mbid="rec-1", title="Test Track", artist="Test Artist", artist_id="art-1"
):
    return {
        "id": mbid,
        "title": title,
        "artist-credit": [
            {"name": artist, "artist": {"id": artist_id, "name": artist}}
        ],
        "length": 240000,
        "first-release-date": "2020-01-01",
        "releases": [{"id": "rel-1", "title": "Test Album", "date": "2020"}],
    }


def _streaming():
    return SimpleNamespace(
        apple_music=None,
        preview=None,
        youtube_video_id="yt123",
        spotify="https://open.spotify.com/track/test",
        artwork=None,
    )


class TestBackgroundLoop:
    def test_runs_the_coroutine_and_returns_its_value(self):
        async def answer():
            return 42

        assert views._run_async(answer()) == 42

    def test_propagates_exceptions_to_the_caller(self):
        async def boom():
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            views._run_async(boom())

    def test_every_call_shares_one_loop(self):
        async def current_loop():
            return asyncio.get_running_loop()

        assert views._run_async(current_loop()) is views._run_async(
            current_loop()
        )

    def test_concurrent_callers_share_the_same_loop(self):
        loops = []

        async def current_loop():
            return asyncio.get_running_loop()

        def call():
            loops.append(views._run_async(current_loop()))

        threads = [threading.Thread(target=call) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(set(id(loop) for loop in loops)) == 1


class TestRandomUrlRouting:
    def test_random_resolves_to_random_tracks_view(self):
        match = resolve("/api/random/")
        assert match.func is random_tracks


class TestRandomEndpoint:
    def test_returns_200_with_tracks_key(self, rf):
        recordings = [
            _recording(mbid=f"rec-{i}", title=f"Track {i}") for i in range(10)
        ]
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success(recordings)),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = random_tracks(rf.get("/api/random/"))

        assert response.status_code == 200
        data = json.loads(response.content)
        assert "tracks" in data

    def test_returns_at_most_five_tracks(self, rf):
        recordings = [
            _recording(mbid=f"rec-{i}", title=f"Track {i}") for i in range(20)
        ]
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success(recordings)),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = random_tracks(rf.get("/api/random/"))

        data = json.loads(response.content)
        assert len(data["tracks"]) <= 5

    def test_each_track_has_required_fields(self, rf):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success([_recording()])),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = random_tracks(rf.get("/api/random/"))

        track = json.loads(response.content)["tracks"][0]
        for field in (
            "mbid",
            "title",
            "artist",
            "artistMbid",
            "durationMs",
            "firstReleaseDate",
            "releases",
            "streaming",
        ):
            assert field in track, f"missing field: {field}"

    def test_streaming_fields_present(self, rf):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success([_recording()])),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = random_tracks(rf.get("/api/random/"))

        streaming = json.loads(response.content)["tracks"][0]["streaming"]
        for field in ("appleMusic", "preview", "youtubeVideoId", "spotify"):
            assert field in streaming, f"missing streaming field: {field}"

    def test_empty_pool_returns_200_with_no_tracks(self, rf):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success([])),
        ):
            response = random_tracks(rf.get("/api/random/"))

        assert response.status_code == 200
        assert json.loads(response.content)["tracks"] == []

    def test_returns_502_when_mb_fails(self, rf):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_error()),
        ):
            response = random_tracks(rf.get("/api/random/"))

        assert response.status_code == 502

    def test_cache_prevents_second_mb_call(self, rf):
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]
        mb_mock = AsyncMock(return_value=_mb_success(recordings))
        with patch("clients.musicbrainz.mb_fetch", new=mb_mock), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            random_tracks(rf.get("/api/random/"))
            random_tracks(rf.get("/api/random/"))

        mb_mock.assert_called_once()

    def test_stale_cache_refetches_from_mb(self, rf):
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]
        mb_mock = AsyncMock(return_value=_mb_success(recordings))
        with patch("clients.musicbrainz.mb_fetch", new=mb_mock), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            random_tracks(rf.get("/api/random/"))
            # Simulate the pool's TTL having elapsed
            views.get_view_cache().delete(views.RANDOM_POOL_KEY)
            random_tracks(rf.get("/api/random/"))

        assert mb_mock.call_count == 2

    def test_serves_stale_pool_when_refresh_fails(self, rf):
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success(recordings)),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            random_tracks(rf.get("/api/random/"))

        views.get_view_cache().delete(views.RANDOM_POOL_KEY)

        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_error()),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = random_tracks(rf.get("/api/random/"))

        assert response.status_code == 200
        assert len(json.loads(response.content)["tracks"]) > 0

    def test_another_worker_holding_the_lock_serves_stale(
        self, rf, sync_cache_enabled
    ):
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]
        mb_mock = AsyncMock(return_value=_mb_success(recordings))
        with patch("clients.musicbrainz.mb_fetch", new=mb_mock), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            random_tracks(rf.get("/api/random/"))

            cache = views.get_view_cache()
            cache.delete(views.RANDOM_POOL_KEY)
            # Stand in for another worker that is mid-refresh
            assert cache.acquire_refresh_slot(views.RANDOM_POOL_LOCK_KEY, 30)

            response = random_tracks(rf.get("/api/random/"))

        assert response.status_code == 200
        mb_mock.assert_called_once()

    def test_a_slow_refresh_does_not_release_the_next_workers_lock(
        self, rf, sync_cache_enabled
    ):
        cache = views.get_view_cache()
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]

        async def slow_build(*args, **kwargs):
            sync_cache_enabled._primary._get_client().delete(
                views.RANDOM_POOL_LOCK_KEY
            )
            cache.acquire_refresh_slot(views.RANDOM_POOL_LOCK_KEY, 30)
            return _mb_success(recordings)

        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(side_effect=slow_build),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            random_tracks(rf.get("/api/random/"))

        retaken = cache.acquire_refresh_slot(views.RANDOM_POOL_LOCK_KEY, 30)
        assert retaken is None

    def test_artist_unknown_when_no_credit(self, rf):
        recording = {
            "id": "rec-no-credit",
            "title": "Mysterious Track",
            "artist-credit": [],
            "length": None,
            "first-release-date": None,
            "releases": [],
        }
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success([recording])),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = random_tracks(rf.get("/api/random/"))

        track = json.loads(response.content)["tracks"][0]
        assert track["artist"] == "Unknown"
        assert track["artistMbid"] == ""
