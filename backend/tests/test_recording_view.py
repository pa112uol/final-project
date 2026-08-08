import json
import pytest
from unittest.mock import AsyncMock, patch
from django.test import RequestFactory
from django.urls import resolve
from api.views import recording


@pytest.fixture
def rf():
    return RequestFactory()


def _resolved(**overrides):
    defaults = {
        "mbid": "resolved-mbid",
        "duration_ms": 238000,
        "album": "The Bends",
        "release_mbid": "release-mbid-1",
        "release_date": "1995-03-13",
    }
    defaults.update(overrides)
    return defaults


def test_resolves_to_recording_view():
    match = resolve("/api/recording/")
    assert match.func is recording


def test_missing_title_returns_400(rf):
    response = recording(rf.get("/api/recording/", {"artist": "Radiohead"}))
    assert response.status_code == 400


def test_blank_title_returns_400(rf):
    response = recording(
        rf.get("/api/recording/", {"title": "  ", "artist": "Radiohead"})
    )
    assert response.status_code == 400


def test_returns_resolved_fields_in_camel_case(rf):
    with patch(
        "recommendations.index.resolve_recording",
        new=AsyncMock(return_value=_resolved()),
    ):
        response = recording(
            rf.get(
                "/api/recording/",
                {"title": "Fake Plastic Trees", "artist": "Radiohead"},
            )
        )
    assert response.status_code == 200
    data = json.loads(response.content)
    assert data == {
        "mbid": "resolved-mbid",
        "durationMs": 238000,
        "firstReleaseDate": "1995-03-13",
        "releases": [
            {
                "mbid": "release-mbid-1",
                "title": "The Bends",
                "date": "1995-03-13",
            }
        ],
    }


def test_returns_empty_releases_when_no_album(rf):
    with patch(
        "recommendations.index.resolve_recording",
        new=AsyncMock(return_value=_resolved(album=None, release_mbid=None)),
    ):
        response = recording(
            rf.get("/api/recording/", {"title": "Obscure Track"})
        )
    data = json.loads(response.content)
    assert data["releases"] == []


def test_echoes_the_supplied_mbid_when_nothing_resolves(rf):
    unresolved = {
        "mbid": "echoed-mbid",
        "duration_ms": None,
        "album": None,
        "release_mbid": None,
        "release_date": None,
    }
    with patch(
        "recommendations.index.resolve_recording",
        new=AsyncMock(return_value=unresolved),
    ):
        response = recording(
            rf.get(
                "/api/recording/",
                {"title": "Obscure Track", "mbid": "echoed-mbid"},
            )
        )
    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["mbid"] == "echoed-mbid"
    assert data["durationMs"] is None
    assert data["firstReleaseDate"] is None
    assert data["releases"] == []


def test_returns_stub_without_touching_musicbrainz_when_source_is_not_lastfm(
    rf, monkeypatch
):
    monkeypatch.setenv("RECORDING_SOURCE", "listenbrainz")

    async def boom(*args, **kwargs):
        raise AssertionError("MusicBrainz should not be called")

    with patch(
        "clients.musicbrainz.resolve_canonical_recording", new=boom
    ):
        response = recording(
            rf.get(
                "/api/recording/",
                {"title": "Alison", "artist": "Slowdive", "mbid": "lb-mbid"},
            )
        )
    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["mbid"] == "lb-mbid"
    assert data["releases"] == []


def test_resolution_failure_falls_back_to_the_echo_stub(rf):
    with patch(
        "recommendations.index.resolve_recording",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        response = recording(
            rf.get(
                "/api/recording/",
                {"title": "Alison", "artist": "Slowdive", "mbid": "orig-mbid"},
            )
        )
    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["mbid"] == "orig-mbid"
    assert data["releases"] == []


def test_post_returns_405(rf):
    response = recording(rf.post("/api/recording/"))
    assert response.status_code == 405
