import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clients.listenbrainz import (
    fetch_recording_tags,
    fetch_artist_top_recordings,
    fetch_recording_popularity,
    fetch_artist_popularity,
)


def make_client(json_data=None, success=True, status_code=200):
    resp = MagicMock()
    resp.is_success = success
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = ""
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    return client, resp


class TestFetchRecordingTags:
    async def test_returns_empty_for_empty_mbid(self):
        assert await fetch_recording_tags("") == []

    async def test_returns_empty_on_http_failure(self):
        client, _ = make_client(success=False, status_code=404)
        with patch("clients.listenbrainz.get_client", return_value=client):
            assert await fetch_recording_tags("abc-mbid") == []

    async def test_merges_tags_from_all_three_sources(self):
        data = {
            "abc-mbid": {
                "tag": {
                    "recording": [{"tag": "rock", "count": 5}],
                    "artist": [{"tag": "indie", "count": 3}],
                    "release_group": [{"tag": "rock", "count": 2}],
                }
            }
        }
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_tags("abc-mbid")
        result_map = {r["name"]: r["count"] for r in result}
        assert result_map["rock"] == 7  # 5 + 2 merged across sources
        assert result_map["indie"] == 3

    async def test_returns_empty_when_no_tag_block(self):
        data = {"abc-mbid": {}}
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_tags("abc-mbid")
        assert result == []

    async def test_skips_entries_with_empty_tag_name(self):
        data = {
            "abc-mbid": {
                "tag": {
                    "recording": [{"tag": "", "count": 5}, {"tag": "jazz", "count": 2}],
                    "artist": [],
                    "release_group": [],
                }
            }
        }
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_tags("abc-mbid")
        assert len(result) == 1
        assert result[0]["name"] == "jazz"

    async def test_lowercases_and_strips_tag_names(self):
        data = {
            "abc-mbid": {
                "tag": {
                    "recording": [{"tag": "  ROCK  ", "count": 1}],
                    "artist": [],
                    "release_group": [],
                }
            }
        }
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_tags("abc-mbid")
        assert result[0]["name"] == "rock"

    async def test_returns_empty_on_exception(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("timeout"))
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_tags("abc-mbid")
        assert result == []


class TestFetchArtistTopRecordings:
    def _good_recording(self, i=0):
        return {
            "recording_mbid": f"rec{i}",
            "recording_name": f"Song {i}",
            "artist_mbids": ["art1"],
            "length": 200000,
            "total_listen_count": 5000 + i,
            "total_user_count": 1000,
            "tags": [{"tag": "rock"}],
        }

    async def test_returns_mapped_recordings(self):
        client, resp = make_client([self._good_recording(0)])
        resp.status_code = 200
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_top_recordings("art1", limit=5)
        assert len(result) == 1
        r = result[0]
        assert r["mbid"] == "rec0"
        assert r["title"] == "Song 0"
        assert r["listen_count"] == 5000
        assert r["tags"] == ["rock"]

    async def test_respects_limit(self):
        data = [self._good_recording(i) for i in range(10)]
        client, resp = make_client(data)
        resp.status_code = 200
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_top_recordings("art1", limit=3)
        assert len(result) == 3

    async def test_skips_recordings_missing_required_fields(self):
        data = [
            {"recording_mbid": "", "recording_name": "Song", "artist_mbids": ["art1"]},
            self._good_recording(1),
        ]
        client, resp = make_client(data)
        resp.status_code = 200
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_top_recordings("art1", limit=10)
        assert len(result) == 1
        assert result[0]["mbid"] == "rec1"

    async def test_returns_empty_on_http_error(self):
        client, resp = make_client(success=False)
        resp.status_code = 500
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_top_recordings("art1", limit=5)
        assert result == []

    async def test_returns_empty_on_exception(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("network error"))
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_top_recordings("art1", limit=5)
        assert result == []

    async def test_retries_once_on_429(self):
        resp = MagicMock()
        resp.status_code = 429
        resp.is_success = False
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)
        with patch("clients.listenbrainz.get_client", return_value=client), \
             patch("clients.listenbrainz.asyncio.sleep", new=AsyncMock()):
            result = await fetch_artist_top_recordings("art1", limit=5)
        assert result == []
        assert client.get.call_count == 2

    async def test_uses_first_artist_mbid_as_artist_mbid(self):
        data = [{
            "recording_mbid": "rec1",
            "recording_name": "Song",
            "artist_mbids": ["primary-art", "secondary-art"],
            "length": None,
            "total_listen_count": 0,
            "total_user_count": 0,
            "tags": [],
        }]
        client, resp = make_client(data)
        resp.status_code = 200
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_top_recordings("primary-art", limit=5)
        assert result[0]["artist_mbid"] == "primary-art"


class TestFetchRecordingPopularity:
    async def test_returns_empty_for_empty_list(self):
        assert await fetch_recording_popularity([]) == {}

    async def test_returns_empty_for_list_of_nones(self):
        assert await fetch_recording_popularity([None, None]) == {}

    async def test_maps_mbid_to_listen_count(self):
        data = [
            {"recording_mbid": "rec1", "total_listen_count": 5000},
            {"recording_mbid": "rec2", "total_listen_count": 1000},
        ]
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_popularity(["rec1", "rec2"])
        assert result == {"rec1": 5000, "rec2": 1000}

    async def test_skips_entries_with_none_listen_count(self):
        data = [
            {"recording_mbid": "rec1", "total_listen_count": None},
            {"recording_mbid": "rec2", "total_listen_count": 200},
        ]
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_popularity(["rec1", "rec2"])
        assert "rec1" not in result
        assert result["rec2"] == 200

    async def test_returns_empty_on_http_failure(self):
        client, _ = make_client(success=False)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_popularity(["rec1"])
        assert result == {}

    async def test_filters_out_none_mbids_before_posting(self):
        data = [{"recording_mbid": "rec1", "total_listen_count": 100}]
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_recording_popularity([None, "rec1", None])
        assert result == {"rec1": 100}
        posted = client.post.call_args.kwargs["json"]["recording_mbids"]
        assert None not in posted
        assert "rec1" in posted


class TestFetchArtistPopularity:
    async def test_returns_empty_for_empty_list(self):
        assert await fetch_artist_popularity([]) == {}

    async def test_maps_artist_mbid_to_listen_count(self):
        data = [{"artist_mbid": "art1", "total_listen_count": 10000}]
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_popularity(["art1"])
        assert result == {"art1": 10000}

    async def test_skips_entries_with_none_listen_count(self):
        data = [
            {"artist_mbid": "art1", "total_listen_count": None},
            {"artist_mbid": "art2", "total_listen_count": 500},
        ]
        client, _ = make_client(data)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_popularity(["art1", "art2"])
        assert "art1" not in result
        assert result["art2"] == 500

    async def test_returns_empty_on_http_failure(self):
        client, _ = make_client(success=False)
        with patch("clients.listenbrainz.get_client", return_value=client):
            result = await fetch_artist_popularity(["art1"])
        assert result == {}
