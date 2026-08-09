from unittest.mock import AsyncMock, MagicMock, patch

from app.routers.coverart import COVERART_NAMESPACE, COVERART_NEGATIVE_TTL_S
from caching.config import TTL_COVERART
from caching.keys import build_key
from caching.local import get_async_view_cache
from clients.coverart import _release_mbids_for_recording, fetch_cover_art_url

# The cache_disabled fixture in conftest.py hands every test a fresh cache, so
# no per-test clearing is needed here any more.


def _coverart_key(mbid: str) -> str:
    return build_key(COVERART_NAMESPACE, mbid)


async def test_missing_mbid_returns_400(api_client):
    response = await api_client.get("/api/coverart/")
    assert response.status_code == 400


async def test_returns_url_when_art_found(api_client):
    expected = "https://archive.org/download/mbid-abc/mbid-abc-500.jpg"
    with patch(
        "clients.coverart.fetch_cover_art_url",
        new=AsyncMock(return_value=expected),
    ):
        response = await api_client.get(
            "/api/coverart/", params={"mbid": "abc-123"}
        )
    assert response.status_code == 200
    assert response.json()["url"] == expected


async def test_returns_404_when_no_art(api_client):
    with patch(
        "clients.coverart.fetch_cover_art_url", new=AsyncMock(return_value=None)
    ):
        response = await api_client.get(
            "/api/coverart/", params={"mbid": "no-art-456"}
        )
    assert response.status_code == 404


async def test_found_url_is_cached_without_re_fetching(api_client):
    mock_fetch = AsyncMock(return_value="https://example.com/art.jpg")
    with patch("clients.coverart.fetch_cover_art_url", new=mock_fetch):
        await api_client.get("/api/coverart/", params={"mbid": "cached-mbid"})
        await api_client.get("/api/coverart/", params={"mbid": "cached-mbid"})
    assert mock_fetch.call_count == 1


async def test_negative_result_is_not_cached_forever(api_client):
    with patch(
        "clients.coverart.fetch_cover_art_url", new=AsyncMock(return_value=None)
    ):
        await api_client.get("/api/coverart/", params={"mbid": "flaky-mbid"})

    # Simulate the negative cache entry's TTL having elapsed
    await get_async_view_cache().delete(_coverart_key("flaky-mbid"))

    with patch(
        "clients.coverart.fetch_cover_art_url",
        new=AsyncMock(return_value="https://example.com/recovered.jpg"),
    ):
        response = await api_client.get(
            "/api/coverart/", params={"mbid": "flaky-mbid"}
        )
    assert response.status_code == 200
    assert response.json()["url"] == "https://example.com/recovered.jpg"


async def test_missing_cover_gets_the_short_negative_ttl(
    api_client, async_view_cache_enabled
):
    with patch(
        "clients.coverart.fetch_cover_art_url", new=AsyncMock(return_value=None)
    ):
        await api_client.get("/api/coverart/", params={"mbid": "no-art-ttl"})

    ttl = await _redis_ttl(async_view_cache_enabled, _coverart_key("no-art-ttl"))
    assert 0 < ttl <= COVERART_NEGATIVE_TTL_S


async def test_found_cover_gets_the_long_positive_ttl(
    api_client, async_view_cache_enabled
):
    with patch(
        "clients.coverart.fetch_cover_art_url",
        new=AsyncMock(return_value="https://example.com/art.jpg"),
    ):
        await api_client.get("/api/coverart/", params={"mbid": "has-art-ttl"})

    ttl = await _redis_ttl(async_view_cache_enabled, _coverart_key("has-art-ttl"))
    assert ttl > COVERART_NEGATIVE_TTL_S
    assert ttl <= TTL_COVERART


async def _redis_ttl(view_cache, key: str) -> int:
    return await view_cache._primary._get_client().ttl(key)


async def test_negative_result_within_ttl_is_not_re_fetched(api_client):
    mock_fetch = AsyncMock(return_value=None)
    with patch("clients.coverart.fetch_cover_art_url", new=mock_fetch):
        await api_client.get("/api/coverart/", params={"mbid": "no-art-789"})
        await api_client.get("/api/coverart/", params={"mbid": "no-art-789"})
    assert mock_fetch.call_count == 1


async def test_passes_release_mbid_through_when_given(api_client):
    mock_fetch = AsyncMock(return_value="https://example.com/art.jpg")
    with patch("clients.coverart.fetch_cover_art_url", new=mock_fetch):
        await api_client.get(
            "/api/coverart/",
            params={"mbid": "rec-1", "releaseMbid": "release-1"},
        )
    mock_fetch.assert_awaited_once_with("rec-1", "release-1")


async def test_blank_release_mbid_is_treated_as_absent(api_client):
    mock_fetch = AsyncMock(return_value="https://example.com/art.jpg")
    with patch("clients.coverart.fetch_cover_art_url", new=mock_fetch):
        await api_client.get(
            "/api/coverart/", params={"mbid": "rec-1", "releaseMbid": "  "}
        )
    mock_fetch.assert_awaited_once_with("rec-1", None)


async def test_missing_release_mbid_is_treated_as_absent(api_client):
    mock_fetch = AsyncMock(return_value="https://example.com/art.jpg")
    with patch("clients.coverart.fetch_cover_art_url", new=mock_fetch):
        await api_client.get("/api/coverart/", params={"mbid": "rec-1"})
    mock_fetch.assert_awaited_once_with("rec-1", None)


async def test_post_returns_405(api_client):
    response = await api_client.post("/api/coverart/")
    assert response.status_code == 405


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
            patch("clients.musicbrainz.get_client", return_value=mock_client),
            patch("clients.musicbrainz.asyncio.sleep", new=AsyncMock()),
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
            patch("clients.musicbrainz.get_client", return_value=mock_client),
            patch("clients.musicbrainz.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _release_mbids_for_recording("some-mbid")
        assert result == []
        assert mock_client.get.call_count == 2


class TestFetchCoverArtUrl:
    async def test_uses_the_given_release_mbid_without_discovering_releases(
        self,
    ):
        with (
            patch(
                "clients.coverart._front_art_url",
                new=AsyncMock(return_value="https://example.com/fast.jpg"),
            ) as mock_front_art,
            patch(
                "clients.coverart._release_mbids_for_recording", new=AsyncMock()
            ) as mock_discover,
        ):
            url = await fetch_cover_art_url("rec-1", release_mbid="release-1")
        assert url == "https://example.com/fast.jpg"
        mock_front_art.assert_awaited_once_with("release-1")
        mock_discover.assert_not_awaited()

    async def test_falls_back_to_discovery_when_given_release_has_no_art(
        self,
    ):
        front_art = AsyncMock(
            side_effect=[None, "https://example.com/found.jpg"]
        )
        with (
            patch("clients.coverart._front_art_url", new=front_art),
            patch(
                "clients.coverart._release_mbids_for_recording",
                new=AsyncMock(return_value=["release-1", "release-2"]),
            ),
        ):
            url = await fetch_cover_art_url("rec-1", release_mbid="release-1")
        assert url == "https://example.com/found.jpg"
        assert front_art.await_count == 2

    async def test_does_not_recheck_the_given_release_during_fallback(self):
        front_art = AsyncMock(
            side_effect=[None, "https://example.com/found.jpg"]
        )
        with (
            patch("clients.coverart._front_art_url", new=front_art),
            patch(
                "clients.coverart._release_mbids_for_recording",
                new=AsyncMock(return_value=["release-1", "release-2"]),
            ),
        ):
            url = await fetch_cover_art_url("rec-1", release_mbid="release-1")
        assert url == "https://example.com/found.jpg"
        checked = [call.args[0] for call in front_art.await_args_list]
        # release-1 checked once via the fast path, not again during fallback
        assert checked == ["release-1", "release-2"]

    async def test_discovers_releases_when_no_release_mbid_given(self):
        with (
            patch(
                "clients.coverart._release_mbids_for_recording",
                new=AsyncMock(return_value=["release-a"]),
            ) as mock_discover,
            patch(
                "clients.coverart._front_art_url",
                new=AsyncMock(return_value="https://example.com/a.jpg"),
            ),
        ):
            url = await fetch_cover_art_url("rec-1")
        assert url == "https://example.com/a.jpg"
        mock_discover.assert_awaited_once_with("rec-1")

    async def test_returns_none_when_nothing_has_art(self):
        with (
            patch(
                "clients.coverart._front_art_url", new=AsyncMock(return_value=None)
            ),
            patch(
                "clients.coverart._release_mbids_for_recording",
                new=AsyncMock(return_value=["release-a"]),
            ),
        ):
            url = await fetch_cover_art_url("rec-1", release_mbid="release-x")
        assert url is None
