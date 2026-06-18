"""Tests for the /api/recommendations/ and /api/search/ endpoints."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from django.test import RequestFactory, override_settings
from django.urls import resolve
import api.views as views
from api.views import recommendations, search


@pytest.fixture
def rf():
    return RequestFactory()


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


class TestRecommendationsUrlRouting:
    def test_recommendations_resolves_to_correct_view(self):
        match = resolve("/api/recommendations/")
        assert match.func is recommendations


class TestRecommendationsView:
    @override_settings(LASTFM_API_KEY="test-api-key")
    def test_returns_400_when_no_mbids(self, rf):
        response = recommendations(rf.get("/api/recommendations/"))
        assert response.status_code == 400
        assert "error" in json.loads(response.content)

    @override_settings(LASTFM_API_KEY="")
    def test_returns_500_when_no_api_key(self, rf):
        response = recommendations(
            rf.get("/api/recommendations/", {"mbid": "rec-1"})
        )
        assert response.status_code == 500
        data = json.loads(response.content)
        assert "LASTFM_API_KEY" in data["error"]

    @override_settings(LASTFM_API_KEY="test-api-key")
    def test_returns_400_for_unknown_mood(self, rf):
        response = recommendations(
            rf.get("/api/recommendations/", {"mbid": "rec-1", "mood": "invalidmood"})
        )
        assert response.status_code == 400
        data = json.loads(response.content)
        assert "mood" in data["error"].lower() or "Unknown mood" in data["error"]

    @override_settings(LASTFM_API_KEY="test-api-key")
    def test_returns_200_with_tracks_on_success(self, rf):
        tracks = [make_track()]
        with patch(
            "recommendations.index.get_recommendations",
            new=AsyncMock(return_value=tracks),
        ):
            response = recommendations(
                rf.get(
                    "/api/recommendations/",
                    {"mbid": "rec-1", "title": "Creep", "artist": "Radiohead"},
                )
            )
        assert response.status_code == 200
        data = json.loads(response.content)
        assert "tracks" in data
        assert len(data["tracks"]) == 1
        assert data["tracks"][0]["mbid"] == "rec-1"

    @override_settings(LASTFM_API_KEY="test-api-key")
    def test_returns_500_when_pipeline_raises(self, rf):
        with patch(
            "recommendations.index.get_recommendations",
            new=AsyncMock(side_effect=Exception("pipeline error")),
        ):
            response = recommendations(
                rf.get("/api/recommendations/", {"mbid": "rec-1"})
            )
        assert response.status_code == 500
        assert "error" in json.loads(response.content)

    @override_settings(LASTFM_API_KEY="test-api-key")
    def test_novelty_clamped_to_0_1(self, rf):
        captured = {}

        async def _capture(*args, **kwargs):
            captured["novelty"] = args[3] if len(args) > 3 else kwargs.get("novelty")
            return []

        with patch("recommendations.index.get_recommendations", new=_capture):
            recommendations(
                rf.get("/api/recommendations/", {"mbid": "rec-1", "novelty": "99"})
            )
        assert captured["novelty"] == 1.0

    @override_settings(LASTFM_API_KEY="test-api-key")
    def test_invalid_novelty_defaults_to_zero(self, rf):
        captured = {}

        async def _capture(*args, **kwargs):
            captured["novelty"] = args[3] if len(args) > 3 else kwargs.get("novelty")
            return []

        with patch("recommendations.index.get_recommendations", new=_capture):
            recommendations(
                rf.get("/api/recommendations/", {"mbid": "rec-1", "novelty": "abc"})
            )
        assert captured["novelty"] == 0.0

    @override_settings(LASTFM_API_KEY="test-api-key")
    def test_multiple_seeds_all_passed_to_pipeline(self, rf):
        captured = {}

        async def _capture(seeds, *args, **kwargs):
            captured["seeds"] = seeds
            return []

        with patch("recommendations.index.get_recommendations", new=_capture):
            recommendations(
                rf.get(
                    "/api/recommendations/",
                    {
                        "mbid": ["rec-1", "rec-2"],
                        "title": ["Song A", "Song B"],
                        "artist": ["Artist A", "Artist B"],
                    },
                )
            )
        assert len(captured["seeds"]) == 2
        assert captured["seeds"][0]["mbid"] == "rec-1"
        assert captured["seeds"][1]["mbid"] == "rec-2"

    @override_settings(LASTFM_API_KEY="test-api-key")
    def test_post_returns_405(self, rf):
        response = recommendations(rf.post("/api/recommendations/"))
        assert response.status_code == 405


class TestSearchView:
    def test_resolves_to_search_view(self):
        match = resolve("/api/search/")
        assert match.func is search

    def test_returns_empty_results_for_blank_query(self, rf):
        response = search(rf.get("/api/search/", {"q": ""}))
        assert response.status_code == 200
        assert json.loads(response.content) == {"results": []}

    def test_returns_empty_results_when_q_absent(self, rf):
        response = search(rf.get("/api/search/"))
        assert response.status_code == 200
        assert json.loads(response.content) == {"results": []}

    def test_returns_mapped_results_on_success(self, rf):
        mb_tracks = [
            {"mbid": "abc", "title": "Creep", "artist": "Radiohead", "score": 95.0}
        ]
        with patch(
            "clients.musicbrainz.search_tracks", new=AsyncMock(return_value=mb_tracks)
        ):
            response = search(rf.get("/api/search/", {"q": "Radiohead Creep"}))
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["results"]) == 1
        r = data["results"][0]
        assert r["type"] == "track"
        assert r["mbid"] == "abc"
        assert r["label"] == "Creep"
        assert r["sub"] == "Radiohead"

    def test_returns_empty_when_search_returns_no_results(self, rf):
        with patch(
            "clients.musicbrainz.search_tracks", new=AsyncMock(return_value=[])
        ):
            response = search(rf.get("/api/search/", {"q": "zzznomatch"}))
        assert response.status_code == 200
        assert json.loads(response.content) == {"results": []}

    def test_post_returns_405(self, rf):
        response = search(rf.post("/api/search/"))
        assert response.status_code == 405
