import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clients.lastfm import (
    _parse_tags,
    fetch_track_tags,
    fetch_track_tags_only,
    fetch_tag_artists,
    fetch_artist_top_tracks,
)


def make_client(json_data=None, success=True):
    resp = MagicMock()
    resp.is_success = success
    resp.json.return_value = json_data or {}
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    return client


class TestParseTags:
    def test_returns_empty_for_none(self):
        assert _parse_tags(None) == []

    def test_returns_empty_for_empty_list(self):
        assert _parse_tags([]) == []

    def test_parses_list_of_tag_dicts(self):
        raw = [{"name": "Rock", "count": "10"}, {"name": "  Pop  ", "count": "5"}]
        result = _parse_tags(raw)
        assert result == [{"name": "rock", "count": 10}, {"name": "pop", "count": 5}]

    def test_wraps_single_dict_in_list(self):
        raw = {"name": "Jazz", "count": "3"}
        result = _parse_tags(raw)
        assert result == [{"name": "jazz", "count": 3}]

    def test_skips_entries_with_empty_name(self):
        raw = [{"name": "", "count": "5"}, {"name": "Rock", "count": "2"}]
        result = _parse_tags(raw)
        assert len(result) == 1
        assert result[0]["name"] == "rock"

    def test_handles_non_integer_count(self):
        raw = [{"name": "Folk", "count": "bad"}]
        result = _parse_tags(raw)
        assert result[0]["count"] == 0

    def test_handles_missing_count_key(self):
        raw = [{"name": "Indie"}]
        result = _parse_tags(raw)
        assert result[0]["count"] == 0

    def test_handles_non_dict_entries(self):
        raw = ["not-a-dict", {"name": "Rock", "count": "2"}]
        result = _parse_tags(raw)
        assert len(result) == 1
        assert result[0]["name"] == "rock"

    def test_lowercases_and_strips_name(self):
        raw = [{"name": "  METAL  ", "count": "7"}]
        result = _parse_tags(raw)
        assert result[0]["name"] == "metal"


class TestFetchTrackTags:
    async def test_returns_track_tags_when_available(self):
        client = make_client({"toptags": {"tag": [{"name": "Rock", "count": "50"}]}})
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_track_tags("Creep", "Radiohead", "key123")
        assert result == [{"name": "rock", "count": 50}]

    async def test_falls_back_to_artist_tags_when_track_has_none(self):
        no_tags_resp = MagicMock()
        no_tags_resp.is_success = True
        no_tags_resp.json.return_value = {"toptags": {"tag": []}}

        artist_resp = MagicMock()
        artist_resp.is_success = True
        artist_resp.json.return_value = {
            "toptags": {"tag": [{"name": "Alternative", "count": "20"}]}
        }

        client = MagicMock()
        client.get = AsyncMock(side_effect=[no_tags_resp, artist_resp])
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_track_tags("Creep", "Radiohead", "key123")
        assert result == [{"name": "alternative", "count": 20}]

    async def test_returns_empty_on_http_failure(self):
        client = make_client(success=False)
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_track_tags("Song", "Artist", "key")
        assert result == []

    async def test_includes_mbid_in_params_when_provided(self):
        client = make_client({"toptags": {"tag": [{"name": "rock", "count": "5"}]}})
        with patch("clients.lastfm.get_client", return_value=client):
            await fetch_track_tags("Song", "Artist", "key", mbid="some-mbid")
        params = client.get.call_args.kwargs["params"]
        assert params.get("mbid") == "some-mbid"

    async def test_omits_mbid_when_not_provided(self):
        client = make_client({"toptags": {"tag": [{"name": "rock", "count": "5"}]}})
        with patch("clients.lastfm.get_client", return_value=client):
            await fetch_track_tags("Song", "Artist", "key")
        params = client.get.call_args.kwargs["params"]
        assert "mbid" not in params


class TestFetchTrackTagsOnly:
    async def test_returns_tags_on_success(self):
        client = make_client({"toptags": {"tag": [{"name": "Pop", "count": "8"}]}})
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_track_tags_only("Song", "Artist", "key")
        assert result == [{"name": "pop", "count": 8}]

    async def test_returns_empty_on_http_failure(self):
        client = make_client(success=False)
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_track_tags_only("Song", "Artist", "key")
        assert result == []

    async def test_does_not_fall_back_to_artist_tags(self):
        client = make_client({"toptags": {"tag": []}})
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_track_tags_only("Song", "Artist", "key")
        assert result == []
        assert client.get.call_count == 1


class TestFetchTagArtists:
    async def test_returns_artist_list_on_success(self):
        client = make_client({
            "topartists": {
                "artist": [
                    {"name": "Radiohead", "mbid": "abc-123"},
                    {"name": "Portishead", "mbid": "def-456"},
                ]
            }
        })
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_tag_artists("trip-hop", 1, 10, "key")
        assert len(result) == 2
        assert result[0] == {"name": "Radiohead", "mbid": "abc-123"}

    async def test_wraps_single_artist_dict(self):
        client = make_client({
            "topartists": {"artist": {"name": "Oasis", "mbid": "xyz"}}
        })
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_tag_artists("britpop", 1, 1, "key")
        assert len(result) == 1
        assert result[0]["name"] == "Oasis"

    async def test_skips_artist_with_empty_name(self):
        client = make_client({
            "topartists": {"artist": [{"name": "", "mbid": "abc"}]}
        })
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_tag_artists("rock", 1, 10, "key")
        assert result == []

    async def test_returns_empty_on_http_failure(self):
        client = make_client(success=False)
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_tag_artists("rock", 1, 10, "key")
        assert result == []

    async def test_returns_empty_when_no_topartists_key(self):
        client = make_client({})
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_tag_artists("jazz", 1, 10, "key")
        assert result == []


class TestFetchArtistTopTracks:
    async def test_returns_track_list_on_success(self):
        tracks = [{"name": "Creep", "playcount": "1000000"}]
        client = make_client({"toptracks": {"track": tracks}})
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_artist_top_tracks("Radiohead", 5, "key")
        assert result == tracks

    async def test_wraps_single_track_dict(self):
        track = {"name": "Creep", "playcount": "1000000"}
        client = make_client({"toptracks": {"track": track}})
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_artist_top_tracks("Radiohead", 1, "key")
        assert result == [track]

    async def test_returns_empty_on_http_failure(self):
        client = make_client(success=False)
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_artist_top_tracks("Artist", 5, "key")
        assert result == []

    async def test_returns_empty_when_no_tracks_key(self):
        client = make_client({})
        with patch("clients.lastfm.get_client", return_value=client):
            result = await fetch_artist_top_tracks("Artist", 5, "key")
        assert result == []
