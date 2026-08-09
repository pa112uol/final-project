from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers.random_tracks import RANDOM_POOL_KEY, RANDOM_POOL_LOCK_KEY
from caching.local import get_async_view_cache


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


# A route registered under a different path or method would 404 here rather
# than reach the view's own logic
async def test_random_route_is_registered(api_client):
    with patch(
        "clients.musicbrainz.mb_fetch",
        new=AsyncMock(return_value=_mb_success([_recording()])),
    ), patch(
        "clients.streaming.get_streaming_links",
        new=AsyncMock(return_value=_streaming()),
    ):
        response = await api_client.get("/api/random/")
    assert response.status_code == 200


class TestRandomEndpoint:
    async def test_returns_200_with_tracks_key(self, api_client):
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
            response = await api_client.get("/api/random/")

        assert response.status_code == 200
        assert "tracks" in response.json()

    async def test_returns_at_most_five_tracks(self, api_client):
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
            response = await api_client.get("/api/random/")

        assert len(response.json()["tracks"]) <= 5

    async def test_each_track_has_required_fields(self, api_client):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success([_recording()])),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = await api_client.get("/api/random/")

        track = response.json()["tracks"][0]
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

    async def test_streaming_fields_present(self, api_client):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success([_recording()])),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = await api_client.get("/api/random/")

        streaming = response.json()["tracks"][0]["streaming"]
        for field in ("appleMusic", "preview", "youtubeVideoId", "spotify"):
            assert field in streaming, f"missing streaming field: {field}"

    async def test_empty_pool_returns_200_with_no_tracks(self, api_client):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success([])),
        ):
            response = await api_client.get("/api/random/")

        assert response.status_code == 200
        assert response.json()["tracks"] == []

    async def test_returns_502_when_mb_fails(self, api_client):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_error()),
        ):
            response = await api_client.get("/api/random/")

        assert response.status_code == 502

    async def test_cache_prevents_second_mb_call(self, api_client):
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]
        mb_mock = AsyncMock(return_value=_mb_success(recordings))
        with patch("clients.musicbrainz.mb_fetch", new=mb_mock), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            await api_client.get("/api/random/")
            await api_client.get("/api/random/")

        mb_mock.assert_called_once()

    async def test_stale_cache_refetches_from_mb(self, api_client):
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]
        mb_mock = AsyncMock(return_value=_mb_success(recordings))
        with patch("clients.musicbrainz.mb_fetch", new=mb_mock), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            await api_client.get("/api/random/")
            # Simulate the pool's TTL having elapsed
            await get_async_view_cache().delete(RANDOM_POOL_KEY)
            await api_client.get("/api/random/")

        assert mb_mock.call_count == 2

    async def test_serves_stale_pool_when_refresh_fails(self, api_client):
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_success(recordings)),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            await api_client.get("/api/random/")

        await get_async_view_cache().delete(RANDOM_POOL_KEY)

        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(return_value=_mb_error()),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            response = await api_client.get("/api/random/")

        assert response.status_code == 200
        assert len(response.json()["tracks"]) > 0

    async def test_another_worker_holding_the_lock_serves_stale(
        self, api_client, async_view_cache_enabled
    ):
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]
        mb_mock = AsyncMock(return_value=_mb_success(recordings))
        with patch("clients.musicbrainz.mb_fetch", new=mb_mock), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            await api_client.get("/api/random/")

            cache = get_async_view_cache()
            await cache.delete(RANDOM_POOL_KEY)
            # Stand in for another worker that is mid-refresh
            assert await cache.acquire_refresh_slot(RANDOM_POOL_LOCK_KEY, 30)

            response = await api_client.get("/api/random/")

        assert response.status_code == 200
        mb_mock.assert_called_once()

    async def test_a_slow_refresh_does_not_release_the_next_workers_lock(
        self, api_client, async_view_cache_enabled
    ):
        cache = get_async_view_cache()
        recordings = [_recording(mbid=f"rec-{i}") for i in range(10)]

        async def slow_build(*args, **kwargs):
            await async_view_cache_enabled._primary._get_client().delete(
                RANDOM_POOL_LOCK_KEY
            )
            await cache.acquire_refresh_slot(RANDOM_POOL_LOCK_KEY, 30)
            return _mb_success(recordings)

        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(side_effect=slow_build),
        ), patch(
            "clients.streaming.get_streaming_links",
            new=AsyncMock(return_value=_streaming()),
        ):
            await api_client.get("/api/random/")

        retaken = await cache.acquire_refresh_slot(RANDOM_POOL_LOCK_KEY, 30)
        assert retaken is None

    async def test_artist_unknown_when_no_credit(self, api_client):
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
            response = await api_client.get("/api/random/")

        track = response.json()["tracks"][0]
        assert track["artist"] == "Unknown"
        assert track["artistMbid"] == ""
