import json
import pytest
from unittest.mock import AsyncMock, patch
from django.test import RequestFactory
import api.views as views
from api.views import coverart


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
