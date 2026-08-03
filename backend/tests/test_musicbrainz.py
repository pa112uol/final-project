import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clients.musicbrainz import (
    _clean,
    _escape_mb,
    _parse_artist_track,
    _build_field_query,
    mb_fetch,
    search_tracks,
    resolve_canonical_mbid,
    resolve_canonical_recording,
    resolve_artist_mbid,
)


# mb_fetch rate-limits between requests and backs off on 429/503; mocking
# sleep keeps every test in this file from paying that delay for real.
@pytest.fixture(autouse=True)
def no_sleep():
    with patch("clients.musicbrainz.asyncio.sleep", new=AsyncMock()):
        yield


def _make_recording(
    mbid="mbid1",
    title="Track",
    artist="Artist",
    score=100,
    releases=None,
    length=None,
):
    rec = {
        "id": mbid,
        "title": title,
        "artist-credit": [{"name": artist}],
        "score": score,
    }
    if releases is not None:
        rec["releases"] = releases
    if length is not None:
        rec["length"] = length
    return rec


def _make_release(title="Album", release_type="Album", date="2000-01-01"):
    return {
        "title": title,
        "date": date,
        "release-group": {"primary-type": release_type},
    }


def _make_response(recordings=None, success=True, status_code=200):
    resp = MagicMock()
    resp.is_success = success
    resp.status_code = status_code
    resp.json.return_value = {
        "recordings": recordings if recordings is not None else []
    }
    return resp


def _patch_client(response):
    """Context manager that patches get_client and returns the mock."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=response)
    patcher = patch("clients.musicbrainz.get_client", return_value=mock_client)
    return patcher


class TestClean:
    def test_strips_whitespace(self):
        assert _clean("  hello  ") == "hello"

    def test_strips_outer_single_quotes(self):
        assert _clean("'Bohemian Rhapsody'") == "Bohemian Rhapsody"

    def test_strips_outer_double_quotes(self):
        assert _clean('"Stairway to Heaven"') == "Stairway to Heaven"

    def test_strips_official_video_suffix(self):
        assert (
            _clean("Bohemian Rhapsody (Official Video)") == "Bohemian Rhapsody"
        )

    def test_strips_official_music_video_suffix(self):
        assert (
            _clean("Smells Like Teen Spirit (Official Music Video)")
            == "Smells Like Teen Spirit"
        )

    def test_strips_lyrics_suffix(self):
        assert _clean("Wonderwall (Lyrics)") == "Wonderwall"

    def test_strips_hd_suffix(self):
        assert _clean("Hotel California [HD]") == "Hotel California"

    def test_strips_remastered_suffix(self):
        assert _clean("Paint It Black (Remastered)") == "Paint It Black"

    def test_collapses_internal_whitespace(self):
        assert _clean("bohemian   rhapsody") == "bohemian rhapsody"

    def test_preserves_normal_text(self):
        assert _clean("Hotel California") == "Hotel California"

    def test_empty_returns_empty(self):
        assert _clean("") == ""

    def test_strips_noise_case_insensitive(self):
        assert _clean("Track (OFFICIAL VIDEO)") == "Track"


class TestEscapeMb:
    def test_escapes_parentheses(self):
        assert _escape_mb("(test)") == r"\(test\)"

    def test_escapes_colon(self):
        assert _escape_mb("a:b") == r"a\:b"

    def test_escapes_brackets(self):
        assert _escape_mb("[HD]") == r"\[HD\]"

    def test_escapes_slash(self):
        assert _escape_mb("a/b") == r"a\/b"

    def test_escapes_dash(self):
        assert _escape_mb("a-b") == r"a\-b"

    def test_escapes_ampersand(self):
        assert _escape_mb("a&b") == r"a\&b"

    def test_plain_text_unchanged(self):
        assert _escape_mb("Bohemian Rhapsody") == "Bohemian Rhapsody"

    def test_empty_string_unchanged(self):
        assert _escape_mb("") == ""


class TestParseArtistTrack:
    def test_dash_separator(self):
        artist, track = _parse_artist_track("Queen - Bohemian Rhapsody")
        assert artist == "Queen"
        assert track == "Bohemian Rhapsody"

    def test_dash_separator_multi_word_artist(self):
        artist, track = _parse_artist_track(
            "The Rolling Stones - Paint It Black"
        )
        assert artist == "The Rolling Stones"
        assert track == "Paint It Black"

    def test_dash_separator_multi_word_both(self):
        artist, track = _parse_artist_track(
            "Red Hot Chili Peppers - Californication"
        )
        assert artist == "Red Hot Chili Peppers"
        assert track == "Californication"

    def test_by_separator(self):
        artist, track = _parse_artist_track("Wonderwall by Oasis")
        assert artist == "Oasis"
        assert track == "Wonderwall"

    def test_by_separator_greedy_handles_by_in_track_name(self):
        artist, track = _parse_artist_track(
            "By The Way by Red Hot Chili Peppers"
        )
        assert artist == "Red Hot Chili Peppers"
        assert track == "By The Way"

    def test_by_case_insensitive(self):
        artist, track = _parse_artist_track(
            "Smells Like Teen Spirit BY Nirvana"
        )
        assert artist == "Nirvana"
        assert track == "Smells Like Teen Spirit"

    def test_no_separator_returns_none_artist(self):
        artist, track = _parse_artist_track("Bohemian Rhapsody")
        assert artist is None
        assert track == "Bohemian Rhapsody"

    def test_single_word_no_separator(self):
        artist, track = _parse_artist_track("Nirvana")
        assert artist is None
        assert track == "Nirvana"


class TestBuildFieldQuery:
    def test_with_artist_uses_artistname_field(self):
        q = _build_field_query("Queen", "Bohemian Rhapsody")
        assert "artistname:" in q
        assert "Bohemian Rhapsody" in q
        assert "Queen" in q

    def test_with_artist_includes_reversed_ordering(self):
        # Both names should appear in phrase positions for correct + reversed branches
        q = _build_field_query("Queen", "Bohemian Rhapsody")
        assert q.count('"Bohemian Rhapsody"') >= 1
        assert q.count('"Queen"') >= 1
        assert " OR " in q

    def test_no_artist_has_phrase_and_recording_branches(self):
        q = _build_field_query(None, "Bohemian Rhapsody")
        assert 'recording:("Bohemian Rhapsody")' in q
        assert "recording:" in q

    def test_no_artist_includes_phrase(self):
        q = _build_field_query(None, "bohemian rhapsody")
        assert '"bohemian rhapsody"' in q

    def test_no_artist_always_fuzzy(self):
        # Fuzzy search always applied when there's no artist, regardless of word count
        for title in ["teen spirit", "the sound of silence simon garfunkel"]:
            assert "~" in _build_field_query(None, title)

    def test_special_chars_escaped(self):
        q = _build_field_query(None, "(What's The Story) Morning Glory")
        assert "\\(" in q or '"' in q

    def test_single_word_includes_fuzzy(self):
        q = _build_field_query(None, "nirvana")
        assert "~" in q

    def test_no_artist_includes_exact_artist_branch_for_single_word(self):
        # The NOT-title artist branch lets a single-word title ("radiohead")
        # surface recordings whose titles don't contain that word ("Creep")
        q = _build_field_query(None, "radiohead")
        assert 'artistname:"radiohead"' in q
        # The branch must exclude title matches so "Wonderwall" beats "Oasis #1"
        assert "-recording:(radiohead~)" in q

    def test_exact_artist_branch_absent_for_multi_word(self):
        # Multi-word titles like "bohemian rhapsody" skip the exact artist branch
        # because multi-word phrases are almost always song titles and there may
        # be an obscure band with that exact name that would flood results.
        q = _build_field_query(None, "bohemian rhapsody")
        assert 'artistname:"bohemian rhapsody"' not in q

    def test_output_is_non_empty_string(self):
        q = _build_field_query(None, "any query")
        assert isinstance(q, str) and len(q) > 0


class TestMbFetch:
    async def test_returns_response_on_success(self):
        resp = _make_response(status_code=200)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=resp)
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await mb_fetch("https://example.com/recording")
        assert result is resp
        assert mock_client.get.call_count == 1

    async def test_passes_params_through(self):
        resp = _make_response(status_code=200)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=resp)
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            await mb_fetch("https://example.com", params={"query": "x"})
        assert mock_client.get.call_args.kwargs["params"] == {"query": "x"}

    async def test_retries_once_on_rate_limit_then_succeeds(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _make_response(success=False, status_code=429),
                _make_response(status_code=200),
            ]
        )
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await mb_fetch("https://example.com")
        assert result.status_code == 200
        assert mock_client.get.call_count == 2

    async def test_gives_up_after_max_attempts(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(
            return_value=_make_response(success=False, status_code=503)
        )
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await mb_fetch("https://example.com")
        assert result.status_code == 503
        assert mock_client.get.call_count == 2

    async def test_non_retryable_error_returns_immediately(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(
            return_value=_make_response(success=False, status_code=404)
        )
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await mb_fetch("https://example.com")
        assert result.status_code == 404
        assert mock_client.get.call_count == 1


class TestSearchTracks:
    async def test_empty_query_returns_empty(self):
        assert await search_tracks("") == []

    async def test_whitespace_only_returns_empty(self):
        assert await search_tracks("   ") == []

    async def test_noise_only_query_returns_empty(self):
        # After _clean, "(Official Video)" reduces to "" => early-exit
        assert await search_tracks("(Official Video)") == []

    async def test_returns_mapped_fields(self):
        rec = _make_recording(mbid="abc", title="Song", artist="Band", score=95)
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Band - Song")
        assert len(results) == 1
        r = results[0]
        assert r["mbid"] == "abc"
        assert r["title"] == "Song"
        assert r["artist"] == "Band"
        assert isinstance(r["score"], float)
        assert r["score"] > 75.0

    async def test_http_error_returns_empty(self):
        with _patch_client(_make_response(success=False, status_code=503)):
            results = await search_tracks("Queen - Bohemian Rhapsody")
        assert results == []

    async def test_exception_returns_empty(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            results = await search_tracks("Queen - Bohemian Rhapsody")
        assert results == []

    async def test_skips_recording_with_no_mbid(self):
        recs = [
            {
                "title": "Song",
                "artist-credit": [{"name": "Artist"}],
                "score": 90,
            },
            _make_recording(
                mbid="good", title="Other", artist="Artist", score=80
            ),
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("Artist")
        assert len(results) == 1
        assert results[0]["mbid"] == "good"

    async def test_deduplicates_by_mbid(self):
        recs = [
            _make_recording(
                mbid="dup", title="Song", artist="Artist", score=90
            ),
            _make_recording(
                mbid="dup", title="Song", artist="Artist", score=80
            ),
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("Artist - Song")
        assert len(results) == 1

    async def test_deduplicates_by_title_artist(self):
        # Same logical track, different mbids - second should be skipped
        recs = [
            _make_recording(
                mbid="id1", title="Song", artist="Artist", score=90
            ),
            _make_recording(
                mbid="id2", title="Song", artist="Artist", score=85
            ),
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("Artist - Song")
        assert len(results) == 1
        assert results[0]["mbid"] == "id1"

    async def test_limits_to_10_results(self):
        recs = [
            _make_recording(
                mbid=str(i), title=f"Song {i}", artist=f"Artist {i}", score=100
            )
            for i in range(20)
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("Song")
        assert len(results) == 10

    async def test_results_sorted_by_score_descending(self):
        recs = [
            _make_recording(
                mbid="exact", title="Creep", artist="Radiohead", score=99
            ),
            _make_recording(
                mbid="partial", title="Creepy", artist="Other", score=75
            ),
            _make_recording(
                mbid="weak", title="Creeper", artist="Band", score=50
            ),
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("Radiohead - Creep")
        assert len(results) >= 1
        for i in range(len(results) - 1):
            assert results[i]["score"] >= results[i + 1]["score"]

    async def test_artist_only_query_surfaces_artists_songs(self):
        # Searching just an artist name must surface that artist's songs even
        # when the track title contains none of the query words.
        recs = [
            _make_recording(
                mbid="by-artist", title="Creep", artist="Radiohead", score=81
            ),
            _make_recording(
                mbid="titled", title="Radiohead", artist="Other Band", score=90
            ),
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("radiohead")
        mbids = [r["mbid"] for r in results]
        assert (
            "by-artist" in mbids
        ), "Artist-name query must surface tracks BY that artist"

    async def test_artist_only_title_match_ranks_above_artist_match(self):
        # A recording whose title matches the query should rank above one that
        # only matches via the artist name (0.75 penalty on artist path).
        recs = [
            _make_recording(
                mbid="title-match", title="Nirvana", artist="Other", score=90
            ),
            _make_recording(
                mbid="artist-match",
                title="Smells Like Teen Spirit",
                artist="Nirvana",
                score=81,
            ),
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("nirvana")
        assert len(results) >= 2
        title_pos = next(
            i for i, r in enumerate(results) if r["mbid"] == "title-match"
        )
        artist_pos = next(
            i for i, r in enumerate(results) if r["mbid"] == "artist-match"
        )
        assert (
            title_pos < artist_pos
        ), "Title match should rank above pure artist match"

    async def test_self_referential_recording_penalised(self):
        # Interviews/compilations with the band name embedded in a longer title
        # ("Interview: There Must Be Another Radiohead") should score lower
        # than a proper song by the same artist that lacks the band name in title.
        recs = [
            # Self-referential: "radiohead" in artist AND in a long title => penalised
            _make_recording(
                mbid="interview",
                title="Interview: There Must Be Another Radiohead",
                artist="Radiohead",
                score=90,
            ),
            # Proper song: "radiohead" only in artist, not in title => not penalised
            _make_recording(
                mbid="song", title="Creep", artist="Radiohead", score=81
            ),
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("radiohead")
        assert len(results) == 2
        song_pos = next(i for i, r in enumerate(results) if r["mbid"] == "song")
        interview_pos = next(
            i for i, r in enumerate(results) if r["mbid"] == "interview"
        )
        assert (
            song_pos < interview_pos
        ), "Proper song must rank above self-referential interview"

    async def test_self_titled_song_not_penalised(self):
        # A self-titled song ("Oasis - Oasis") has the same word count as
        # the query, so the ≥q_words+2 guard prevents the penalty from firing.
        recs = [
            _make_recording(
                mbid="self-titled", title="Oasis", artist="Oasis", score=90
            )
        ]
        with _patch_client(_make_response(recs)):
            results = await search_tracks("oasis")
        # Should not be penalised; score must be above the base level for a
        # pure title match (rf≈100, no penalty)
        assert len(results) == 1
        assert results[0]["score"] > 60.0

    async def test_empty_artist_credit_yields_empty_artist(self):
        rec = {"id": "abc", "title": "Track", "artist-credit": [], "score": 70}
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Track")
        assert results[0]["artist"] == ""

    async def test_none_artist_credit_yields_empty_artist(self):
        rec = {
            "id": "abc",
            "title": "Track",
            "artist-credit": None,
            "score": 70,
        }
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Track")
        assert results[0]["artist"] == ""

    async def test_null_recordings_key_returns_empty(self):
        resp = MagicMock()
        resp.is_success = True
        resp.json.return_value = {"recordings": None}
        with _patch_client(resp):
            results = await search_tracks("anything")
        assert results == []

    async def test_returns_album_title_and_release_type_from_first_release(
        self,
    ):
        release = _make_release(title="OK Computer", release_type="Album")
        rec = _make_recording(releases=[release])
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Track")
        assert results[0]["album"] == "OK Computer"
        assert results[0]["release_type"] == "Album"

    async def test_returns_year_from_release_date(self):
        release = _make_release(date="1997-05-21")
        rec = _make_recording(releases=[release])
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Track")
        assert results[0]["year"] == "1997"

    async def test_year_from_first_release_date_takes_priority(self):
        release = _make_release(date="1999-01-01")
        rec = _make_recording(releases=[release])
        rec["first-release-date"] = "1997-05-21"
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Track")
        assert results[0]["year"] == "1997"

    async def test_year_falls_back_to_release_date_when_no_first_release_date(
        self,
    ):
        release = _make_release(date="1997-05-21")
        rec = _make_recording(releases=[release])
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Track")
        assert results[0]["year"] == "1997"

    async def test_album_year_release_type_none_when_no_releases(self):
        rec = _make_recording()
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Track")
        assert results[0]["album"] is None
        assert results[0]["release_type"] is None
        assert results[0]["year"] is None

    async def test_year_none_when_date_missing(self):
        release = {
            "title": "Some Album",
            "release-group": {"primary-type": "Album"},
        }
        rec = _make_recording(releases=[release])
        with _patch_client(_make_response([rec])):
            results = await search_tracks("Track")
        assert results[0]["year"] is None


class TestResolveCanonicalMbid:
    async def test_resolves_by_search_ignoring_given_mbid(self):
        search_resp = _make_response(
            [
                _make_recording(
                    mbid="found-id", title="Bohemian Rhapsody", artist="Queen"
                )
            ]
        )
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=search_resp)
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await resolve_canonical_mbid(
                "stale-id", "Bohemian Rhapsody", "Queen"
            )
        assert result == "found-id"
        assert mock_client.get.call_count == 1
        assert "stale-id" not in mock_client.get.call_args.args[0]

    async def test_resolves_by_search_when_no_mbid_provided(self):
        search_resp = _make_response(
            [
                _make_recording(
                    mbid="found-id", title="Creep", artist="Radiohead"
                )
            ]
        )
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=search_resp)
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await resolve_canonical_mbid("", "Creep", "Radiohead")
        assert result == "found-id"
        assert mock_client.get.call_count == 1

    async def test_returns_original_mbid_when_search_finds_nothing(self):
        search_resp = _make_response([])
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=search_resp)
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await resolve_canonical_mbid(
                "original-id", "Some Obscure Track", "Some Artist"
            )
        assert result == "original-id"

    async def test_returns_original_mbid_when_search_http_fails(self):
        search_resp = _make_response(success=False, status_code=503)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=search_resp)
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await resolve_canonical_mbid(
                "original-id", "Bohemian Rhapsody", "Queen"
            )
        assert result == "original-id"

    async def test_returns_original_mbid_when_search_raises(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await resolve_canonical_mbid(
                "original-id", "Bohemian Rhapsody", "Queen"
            )
        assert result == "original-id"

    async def test_no_request_when_no_title_given(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock()
        with patch("clients.musicbrainz.get_client", return_value=mock_client):
            result = await resolve_canonical_mbid("original-id")
        assert result == "original-id"
        assert mock_client.get.call_count == 0


class TestResolveCanonicalRecording:
    async def test_returns_mbid_duration_and_album_from_search(self):
        release = _make_release(
            title="A Night at the Opera",
            release_type="Album",
            date="1975-11-21",
        )
        release["id"] = "release-id"
        search_resp = _make_response(
            [
                _make_recording(
                    mbid="found-id",
                    title="Bohemian Rhapsody",
                    artist="Queen",
                    length=354000,
                    releases=[release],
                )
            ]
        )
        with _patch_client(search_resp):
            result = await resolve_canonical_recording(
                "stale-id", "Bohemian Rhapsody", "Queen"
            )
        assert result == {
            "mbid": "found-id",
            "duration_ms": 354000,
            "album": "A Night at the Opera",
            "release_mbid": "release-id",
            "release_date": "1975-11-21",
        }

    async def test_returns_original_mbid_and_no_data_when_search_finds_nothing(
        self,
    ):
        with _patch_client(_make_response([])):
            result = await resolve_canonical_recording(
                "original-id", "Some Obscure Track", "Some Artist"
            )
        assert result == {
            "mbid": "original-id",
            "duration_ms": None,
            "album": None,
            "release_mbid": None,
            "release_date": None,
        }


def make_mb_resp(artists, success=True):
    resp = MagicMock()
    resp.is_success = success
    resp.json.return_value = {"artists": artists}
    return AsyncMock(return_value=resp)


class TestResolveArtistMbid:
    async def test_returns_artist_id_when_score_above_threshold(self):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=make_mb_resp([{"id": "abc-123", "score": 95}]),
        ):
            result = await resolve_artist_mbid("Radiohead")
        assert result == "abc-123"

    async def test_returns_artist_id_when_score_exactly_85(self):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=make_mb_resp([{"id": "abc-123", "score": 85}]),
        ):
            result = await resolve_artist_mbid("Radiohead")
        assert result == "abc-123"

    async def test_returns_empty_when_score_below_85(self):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=make_mb_resp([{"id": "abc-123", "score": 84}]),
        ):
            result = await resolve_artist_mbid("Unknown Band")
        assert result == ""

    async def test_returns_empty_when_no_artists(self):
        with patch("clients.musicbrainz.mb_fetch", new=make_mb_resp([])):
            result = await resolve_artist_mbid("Nonexistent")
        assert result == ""

    async def test_returns_empty_on_http_failure(self):
        resp = MagicMock()
        resp.is_success = False
        with patch(
            "clients.musicbrainz.mb_fetch", new=AsyncMock(return_value=resp)
        ):
            result = await resolve_artist_mbid("Artist")
        assert result == ""

    async def test_returns_empty_on_exception(self):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=AsyncMock(side_effect=Exception("timeout")),
        ):
            result = await resolve_artist_mbid("Artist")
        assert result == ""

    async def test_strips_double_quotes_from_name_before_querying(self):
        mock_fetch = make_mb_resp([{"id": "abc-123", "score": 90}])
        with patch("clients.musicbrainz.mb_fetch", new=mock_fetch):
            await resolve_artist_mbid('AC"DC')
        query = mock_fetch.call_args.kwargs["params"]["query"]
        assert '"' not in query.replace('artist:"', "").replace('"', "")

    async def test_uses_first_artist_in_response(self):
        artists = [
            {"id": "first-id", "score": 92},
            {"id": "second-id", "score": 88},
        ]
        with patch("clients.musicbrainz.mb_fetch", new=make_mb_resp(artists)):
            result = await resolve_artist_mbid("Oasis")
        assert result == "first-id"

    async def test_missing_score_treated_as_zero(self):
        with patch(
            "clients.musicbrainz.mb_fetch",
            new=make_mb_resp([{"id": "abc-123"}]),
        ):
            result = await resolve_artist_mbid("Artist")
        assert result == ""
