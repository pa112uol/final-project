from unittest.mock import AsyncMock, patch


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


# A route registered under a different path or method would 404 here rather
# than reach the view's own validation
async def test_recording_route_is_registered(api_client):
    response = await api_client.get("/api/recording/")
    assert response.status_code == 400


async def test_missing_title_returns_400(api_client):
    response = await api_client.get(
        "/api/recording/", params={"artist": "Radiohead"}
    )
    assert response.status_code == 400


async def test_blank_title_returns_400(api_client):
    response = await api_client.get(
        "/api/recording/", params={"title": "  ", "artist": "Radiohead"}
    )
    assert response.status_code == 400


async def test_returns_resolved_fields_in_camel_case(api_client):
    with patch(
        "recommendations.index.resolve_recording",
        new=AsyncMock(return_value=_resolved()),
    ):
        response = await api_client.get(
            "/api/recording/",
            params={"title": "Fake Plastic Trees", "artist": "Radiohead"},
        )
    assert response.status_code == 200
    assert response.json() == {
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


async def test_returns_empty_releases_when_no_album(api_client):
    with patch(
        "recommendations.index.resolve_recording",
        new=AsyncMock(return_value=_resolved(album=None, release_mbid=None)),
    ):
        response = await api_client.get(
            "/api/recording/", params={"title": "Obscure Track"}
        )
    assert response.json()["releases"] == []


async def test_echoes_the_supplied_mbid_when_nothing_resolves(api_client):
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
        response = await api_client.get(
            "/api/recording/",
            params={"title": "Obscure Track", "mbid": "echoed-mbid"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["mbid"] == "echoed-mbid"
    assert data["durationMs"] is None
    assert data["firstReleaseDate"] is None
    assert data["releases"] == []


async def test_resolution_failure_falls_back_to_the_echo_stub(api_client):
    with patch(
        "recommendations.index.resolve_recording",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        response = await api_client.get(
            "/api/recording/",
            params={"title": "Alison", "artist": "Slowdive", "mbid": "orig-mbid"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["mbid"] == "orig-mbid"
    assert data["releases"] == []


async def test_post_returns_405(api_client):
    response = await api_client.post("/api/recording/")
    assert response.status_code == 405
