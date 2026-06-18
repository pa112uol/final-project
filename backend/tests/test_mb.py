import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clients.mb import resolve_artist_mbid


def make_mb_resp(artists, success=True):
    resp = MagicMock()
    resp.is_success = success
    resp.json.return_value = {"artists": artists}
    return AsyncMock(return_value=resp)


class TestResolveArtistMbid:
    async def test_returns_artist_id_when_score_above_threshold(self):
        with patch("clients.mb.mb_fetch", new=make_mb_resp([{"id": "abc-123", "score": 95}])):
            result = await resolve_artist_mbid("Radiohead")
        assert result == "abc-123"

    async def test_returns_artist_id_when_score_exactly_85(self):
        with patch("clients.mb.mb_fetch", new=make_mb_resp([{"id": "abc-123", "score": 85}])):
            result = await resolve_artist_mbid("Radiohead")
        assert result == "abc-123"

    async def test_returns_empty_when_score_below_85(self):
        with patch("clients.mb.mb_fetch", new=make_mb_resp([{"id": "abc-123", "score": 84}])):
            result = await resolve_artist_mbid("Unknown Band")
        assert result == ""

    async def test_returns_empty_when_no_artists(self):
        with patch("clients.mb.mb_fetch", new=make_mb_resp([])):
            result = await resolve_artist_mbid("Nonexistent")
        assert result == ""

    async def test_returns_empty_on_http_failure(self):
        resp = MagicMock()
        resp.is_success = False
        with patch("clients.mb.mb_fetch", new=AsyncMock(return_value=resp)):
            result = await resolve_artist_mbid("Artist")
        assert result == ""

    async def test_returns_empty_on_exception(self):
        with patch("clients.mb.mb_fetch", new=AsyncMock(side_effect=Exception("timeout"))):
            result = await resolve_artist_mbid("Artist")
        assert result == ""

    async def test_strips_double_quotes_from_name_before_querying(self):
        mock_fetch = make_mb_resp([{"id": "abc-123", "score": 90}])
        with patch("clients.mb.mb_fetch", new=mock_fetch):
            await resolve_artist_mbid('AC"DC')
        url = mock_fetch.call_args[0][0]
        assert '"' not in url.split("query=")[1].split("&")[0].replace('artist:"', "").replace('"', "")

    async def test_uses_first_artist_in_response(self):
        artists = [
            {"id": "first-id", "score": 92},
            {"id": "second-id", "score": 88},
        ]
        with patch("clients.mb.mb_fetch", new=make_mb_resp(artists)):
            result = await resolve_artist_mbid("Oasis")
        assert result == "first-id"

    async def test_missing_score_treated_as_zero(self):
        with patch("clients.mb.mb_fetch", new=make_mb_resp([{"id": "abc-123"}])):
            result = await resolve_artist_mbid("Artist")
        assert result == ""
