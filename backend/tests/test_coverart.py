import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from django.test import RequestFactory
import api.views as views
from api.views import coverart
from clients.coverart import _release_mbids_for_recording


@pytest.fixture(autouse=True)
def clear_coverart_cache():
    views._coverart_cache.clear()


@pytest.fixture
def rf():
    return RequestFactory()


def test_missing_mbid_returns_400(rf):
    response = coverart(rf.get("/api/coverart/"))
    assert response.status_code == 400


def test_returns_url_when_art_found(rf):
    expected = "https://archive.org/download/mbid-abc/mbid-abc-500.jpg"
    with patch("clients.coverart.fetch_cover_art_url", new=AsyncMock(return_value=expected)):
        response = coverart(rf.get("/api/coverart/", {"mbid": "abc-123"}))
    assert response.status_code == 200
    assert json.loads(response.content)["url"] == expected


def test_returns_404_when_no_art(rf):
    with patch("clients.coverart.fetch_cover_art_url", new=AsyncMock(return_value=None)):
        response = coverart(rf.get("/api/coverart/", {"mbid": "no-art-456"}))
    assert response.status_code == 404


def test_found_url_is_cached_without_re_fetching(rf):
    mock_fetch = AsyncMock(return_value="https://example.com/art.jpg")
    with patch("clients.coverart.fetch_cover_art_url", new=mock_fetch):
        coverart(rf.get("/api/coverart/", {"mbid": "cached-mbid"}))
        coverart(rf.get("/api/coverart/", {"mbid": "cached-mbid"}))
    assert mock_fetch.call_count == 1


def test_negative_result_is_not_cached_forever(rf):
    with patch("clients.coverart.fetch_cover_art_url", new=AsyncMock(return_value=None)):
        coverart(rf.get("/api/coverart/", {"mbid": "flaky-mbid"}))

    # Simulate the negative cache entry's TTL having elapsed
    url, _ = views._coverart_cache["flaky-mbid"]
    views._coverart_cache["flaky-mbid"] = (url, 0)

    with patch(
        "clients.coverart.fetch_cover_art_url",
        new=AsyncMock(return_value="https://example.com/recovered.jpg"),
    ):
        response = coverart(rf.get("/api/coverart/", {"mbid": "flaky-mbid"}))
    assert response.status_code == 200
    assert json.loads(response.content)["url"] == "https://example.com/recovered.jpg"


def test_negative_result_within_ttl_is_not_re_fetched(rf):
    mock_fetch = AsyncMock(return_value=None)
    with patch("clients.coverart.fetch_cover_art_url", new=mock_fetch):
        coverart(rf.get("/api/coverart/", {"mbid": "no-art-789"}))
        coverart(rf.get("/api/coverart/", {"mbid": "no-art-789"}))
    assert mock_fetch.call_count == 1


def _mb_response(status_code, releases=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = status_code == 200
    resp.json.return_value = {"releases": releases or []}
    return resp


class TestReleaseMbidsForRecording:
    async def test_retries_once_on_rate_limit_then_succeeds(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _mb_response(429),
                _mb_response(200, releases=[{"id": "release-1"}]),
            ]
        )
        with (
            patch("clients.coverart.get_client", return_value=mock_client),
            patch("clients.coverart.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _release_mbids_for_recording("some-mbid")
        assert result == ["release-1"]
        assert mock_client.get.call_count == 2

    async def test_gives_up_after_second_rate_limit(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(
            side_effect=[_mb_response(503), _mb_response(503)]
        )
        with (
            patch("clients.coverart.get_client", return_value=mock_client),
            patch("clients.coverart.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _release_mbids_for_recording("some-mbid")
        assert result == []
        assert mock_client.get.call_count == 2
