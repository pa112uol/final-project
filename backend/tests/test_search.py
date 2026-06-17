"""Unit tests for search query building and input normalisation."""
import pytest
from clients.musicbrainz import _clean, _parse_artist_track, _build_query


class TestClean:
    def test_strips_whitespace(self):
        assert _clean("  hello  ") == "hello"

    def test_strips_outer_single_quotes(self):
        assert _clean("'Bohemian Rhapsody'") == "Bohemian Rhapsody"

    def test_strips_outer_double_quotes(self):
        assert _clean('"Stairway to Heaven"') == "Stairway to Heaven"

    def test_strips_official_video_suffix(self):
        assert _clean("Bohemian Rhapsody (Official Video)") == "Bohemian Rhapsody"

    def test_strips_official_music_video_suffix(self):
        assert _clean("Smells Like Teen Spirit (Official Music Video)") == "Smells Like Teen Spirit"

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


class TestParseArtistTrack:
    def test_dash_separator(self):
        artist, track = _parse_artist_track("Queen - Bohemian Rhapsody")
        assert artist == "Queen"
        assert track == "Bohemian Rhapsody"

    def test_dash_separator_multi_word_artist(self):
        artist, track = _parse_artist_track("The Rolling Stones - Paint It Black")
        assert artist == "The Rolling Stones"
        assert track == "Paint It Black"

    def test_dash_separator_multi_word_both(self):
        artist, track = _parse_artist_track("Red Hot Chili Peppers - Californication")
        assert artist == "Red Hot Chili Peppers"
        assert track == "Californication"

    def test_by_separator(self):
        artist, track = _parse_artist_track("Wonderwall by Oasis")
        assert artist == "Oasis"
        assert track == "Wonderwall"

    def test_by_separator_greedy_handles_by_in_track_name(self):
        # "By The Way" should stay as track, "RHCP" as artist
        artist, track = _parse_artist_track("By The Way by Red Hot Chili Peppers")
        assert artist == "Red Hot Chili Peppers"
        assert track == "By The Way"

    def test_by_case_insensitive(self):
        artist, track = _parse_artist_track("Smells Like Teen Spirit BY Nirvana")
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


class TestBuildQuery:
    def test_dash_query_uses_artistname_field(self):
        q = _build_query("Queen - Bohemian Rhapsody")
        assert "artistname:" in q
        assert "Bohemian Rhapsody" in q
        assert "Queen" in q

    def test_dash_query_includes_reversed_fallback(self):
        q = _build_query("Queen - Bohemian Rhapsody")
        assert '"Bohemian Rhapsody"' in q
        assert '"Queen"' in q
        assert q.count(" OR ") >= 1  # at least correct + reversed branch

    def test_plain_query_always_fuzzy(self):
        # All plain queries now always use ~- no word-count condition.
        for query in ["creep", "teen spirit", "the sound of silence simon garfunkel"]:
            assert "~" in _build_query(query)

    def test_plain_query_has_phrase_branch(self):
        # Phrase branch ensures "bohemian rhapsody" finds Queen even though
        # "Queen" contains no matching tokens.
        q = _build_query("bohemian rhapsody")
        assert '"bohemian rhapsody"' in q

    def test_plain_query_has_recording_only_fuzzy_branch(self):
        # The last branch has no artistname: constraint so track-name-only
        # queries like "bohemian rapsody" (typo) still surface Queen.
        q = _build_query("bohemian rapsody")
        parts = q.split(" OR ")
        no_artist = [p for p in parts if "artistname:" not in p and "~" in p]
        assert len(no_artist) > 0

    def test_plain_cross_field_and_for_artist_track(self):
        # "radiohead creep" must include a cross-field branch so "Creep" by
        # Radiohead ranks high: recording matches "creep~", artistname "radiohead~".
        q = _build_query("radiohead creep")
        assert "AND artistname:" in q

    def test_by_separator_swaps_artist_and_track(self):
        q = _build_query("Bohemian Rhapsody by Queen")
        assert "Queen" in q
        assert "Bohemian Rhapsody" in q
        assert "artistname:" in q

    def test_feat_stripped_from_track(self):
        q = _build_query("Queen - Bohemian Rhapsody feat. David Bowie")
        assert "David Bowie" not in q

    def test_feat_stripped_from_plain_query(self):
        q = _build_query("Bohemian Rhapsody feat. David Bowie")
        assert "David Bowie" not in q

    def test_special_chars_escaped(self):
        q = _build_query("(What's The Story) Morning Glory")
        assert "\\(" in q or '"' in q

    def test_plain_query_includes_exact_artist_branch(self):
        q = _build_query("radiohead")
        assert 'artistname:"radiohead"' in q
        assert '-recording:(radiohead~)' in q

    def test_exact_artist_branch_absent_for_multi_word(self):
        q = _build_query("bohemian rhapsody")
        assert 'artistname:"bohemian rhapsody"' not in q

    def test_output_is_non_empty_string(self):
        q = _build_query("any query")
        assert isinstance(q, str) and len(q) > 0
