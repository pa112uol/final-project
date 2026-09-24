import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.deps import get_pipeline_semaphore, get_settings_dependency
from app.main import app


def make_track(mbid="rec-1", title="Creep", artist="Radiohead"):
    t = MagicMock()
    t.to_dict.return_value = {
        "mbid": mbid,
        "title": title,
        "artist": artist,
        "artistMbid": "art-1",
        "durationMs": 238000,
        "firstReleaseDate": "1992-09-21",
        "releases": [],
        "streaming": {
            "appleMusic": None,
            "preview": None,
            "youtubeVideoId": None,
            "spotify": "https://open.spotify.com/search/Radiohead%20Creep",
        },
        "relevanceScore": 0.8,
        "noveltyScore": 0.3,
        "tags": ["alternative"],
    }
    return t


# Overrides the get_settings dependency for the duration of one test
@pytest.fixture
def with_settings():
    def _apply(**overrides):
        overrides.setdefault("lastfm_api_key", "test-api-key")
        app.dependency_overrides[get_settings_dependency] = lambda: Settings(
            **overrides
        )

    yield _apply
    app.dependency_overrides.pop(get_settings_dependency, None)


class TestRecommendationsUrlRouting:
    # A route registered under a different path or method would 404 here
    # rather than reach the view's own validation
    async def test_recommendations_route_is_registered(
        self, api_client, with_settings
    ):
        with_settings()
        response = await api_client.get("/api/recommendations/")
        assert response.status_code == 400


class TestRecommendationsView:
    async def test_returns_400_when_no_mbids(self, api_client, with_settings):
        with_settings()
        response = await api_client.get("/api/recommendations/")
        assert response.status_code == 400
        assert "error" in response.json()

    async def test_returns_500_when_no_api_key(self, api_client, with_settings):
        with_settings(lastfm_api_key="")
        response = await api_client.get(
            "/api/recommendations/", params={"mbid": "rec-1"}
        )
        assert response.status_code == 500
        data = response.json()
        assert "LASTFM_API_KEY" in data["error"]

    async def test_returns_400_for_unknown_mood(
        self, api_client, with_settings
    ):
        with_settings()
        response = await api_client.get(
            "/api/recommendations/",
            params={"mbid": "rec-1", "mood": "invalidmood"},
        )
        assert response.status_code == 400
        data = response.json()
        assert (
            "mood" in data["error"].lower() or "Unknown mood" in data["error"]
        )

    async def test_returns_200_with_tracks_on_success(
        self, api_client, with_settings
    ):
        with_settings()
        tracks = [make_track()]
        with patch(
            "recommendations.index.get_recommendations",
            new=AsyncMock(return_value=tracks),
        ):
            response = await api_client.get(
                "/api/recommendations/",
                params={
                    "mbid": "rec-1",
                    "title": "Creep",
                    "artist": "Radiohead",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert "tracks" in data
        assert len(data["tracks"]) == 1
        assert data["tracks"][0]["mbid"] == "rec-1"

    async def test_returns_500_when_pipeline_raises(
        self, api_client, with_settings
    ):
        with_settings()
        with patch(
            "recommendations.index.get_recommendations",
            new=AsyncMock(side_effect=Exception("pipeline error")),
        ):
            response = await api_client.get(
                "/api/recommendations/", params={"mbid": "rec-1"}
            )
        assert response.status_code == 500
        assert "error" in response.json()

    async def test_returns_504_when_pipeline_times_out(
        self, api_client, with_settings
    ):
        with_settings()

        async def _hangs(*args, **kwargs):
            import asyncio

            await asyncio.sleep(10)

        with (
            patch("recommendations.index.get_recommendations", new=_hangs),
            patch("app.routers.recommendations.PIPELINE_TIMEOUT_S", 0.01),
        ):
            response = await api_client.get(
                "/api/recommendations/", params={"mbid": "rec-1"}
            )
        assert response.status_code == 504
        assert "error" in response.json()

    # PIPELINE_TIMEOUT_S must bound the wait for a free
    # semaphore slot not just the pipeline run once one is acquired
    async def test_timeout_bounds_the_semaphore_wait(
        self, api_client, with_settings
    ):
        with_settings()
        exhausted = asyncio.Semaphore(
            0
        )  # already fully held, acquire() never returns
        app.dependency_overrides[get_pipeline_semaphore] = lambda: exhausted
        pipeline = AsyncMock(return_value=[])
        try:
            with (
                patch(
                    "recommendations.index.get_recommendations", new=pipeline
                ),
                patch("app.routers.recommendations.PIPELINE_TIMEOUT_S", 0.05),
            ):
                response = await api_client.get(
                    "/api/recommendations/", params={"mbid": "rec-1"}
                )
        finally:
            app.dependency_overrides.pop(get_pipeline_semaphore, None)

        assert response.status_code == 504
        pipeline.assert_not_awaited()

    async def test_novelty_clamped_to_0_1(self, api_client, with_settings):
        with_settings()
        captured = {}

        async def _capture(*args, **kwargs):
            captured["novelty"] = (
                args[3] if len(args) > 3 else kwargs.get("novelty")
            )
            return []

        with patch("recommendations.index.get_recommendations", new=_capture):
            await api_client.get(
                "/api/recommendations/",
                params={"mbid": "rec-1", "novelty": "99"},
            )
        assert captured["novelty"] == 1.0

    async def test_invalid_novelty_defaults_to_zero(
        self, api_client, with_settings
    ):
        with_settings()
        captured = {}

        async def _capture(*args, **kwargs):
            captured["novelty"] = (
                args[3] if len(args) > 3 else kwargs.get("novelty")
            )
            return []

        with patch("recommendations.index.get_recommendations", new=_capture):
            await api_client.get(
                "/api/recommendations/",
                params={"mbid": "rec-1", "novelty": "abc"},
            )
        assert captured["novelty"] == 0.0

    async def test_multiple_seeds_all_passed_to_pipeline(
        self, api_client, with_settings
    ):
        with_settings()
        captured = {}

        async def _capture(seeds, *args, **kwargs):
            captured["seeds"] = seeds
            return []

        with patch("recommendations.index.get_recommendations", new=_capture):
            await api_client.get(
                "/api/recommendations/",
                params={
                    "mbid": ["rec-1", "rec-2"],
                    "title": ["Song A", "Song B"],
                    "artist": ["Artist A", "Artist B"],
                },
            )
        assert len(captured["seeds"]) == 2
        assert captured["seeds"][0]["mbid"] == "rec-1"
        assert captured["seeds"][1]["mbid"] == "rec-2"

    # Regression test for MAX_SEED_TRACKS truncation, which the Django-era
    # suite never exercised past 2 seeds
    async def test_seeds_beyond_max_seed_tracks_are_dropped(
        self, api_client, with_settings
    ):
        with_settings(max_seed_tracks=3)
        captured = {}

        async def _capture(seeds, *args, **kwargs):
            captured["seeds"] = seeds
            return []

        mbids = [f"rec-{i}" for i in range(6)]
        with patch("recommendations.index.get_recommendations", new=_capture):
            await api_client.get(
                "/api/recommendations/", params={"mbid": mbids}
            )
        assert len(captured["seeds"]) == 3
        assert [s["mbid"] for s in captured["seeds"]] == mbids[:3]

    async def test_post_returns_405(self, api_client, with_settings):
        with_settings()
        response = await api_client.post("/api/recommendations/")
        assert response.status_code == 405


class TestSearchView:
    async def test_returns_empty_results_for_blank_query(self, api_client):
        response = await api_client.get("/api/search/", params={"q": ""})
        assert response.status_code == 200
        assert response.json() == {"results": []}

    async def test_returns_empty_results_when_q_absent(self, api_client):
        response = await api_client.get("/api/search/")
        assert response.status_code == 200
        assert response.json() == {"results": []}

    async def test_returns_mapped_results_on_success(self, api_client):
        mb_tracks = [
            {
                "mbid": "abc",
                "title": "Creep",
                "artist": "Radiohead",
                "score": 95.0,
            }
        ]
        with patch(
            "clients.musicbrainz.search_tracks",
            new=AsyncMock(return_value=mb_tracks),
        ):
            response = await api_client.get(
                "/api/search/", params={"q": "Radiohead Creep"}
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        r = data["results"][0]
        assert r["type"] == "track"
        assert r["mbid"] == "abc"
        assert r["label"] == "Creep"
        assert r["sub"] == "Radiohead"

    async def test_returns_empty_when_search_returns_no_results(
        self, api_client
    ):
        with patch(
            "clients.musicbrainz.search_tracks", new=AsyncMock(return_value=[])
        ):
            response = await api_client.get(
                "/api/search/", params={"q": "zzznomatch"}
            )
        assert response.status_code == 200
        assert response.json() == {"results": []}

    async def test_post_returns_405(self, api_client):
        response = await api_client.post("/api/search/")
        assert response.status_code == 405
