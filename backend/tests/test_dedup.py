import pytest
from recommendations.dedup import (
    normalize_title,
    titles_overlap,
    filter_seeds,
    deduplicate_by_mbid,
    deduplicate_by_title,
)
from recommendations.types import Candidate, Seed


def make_candidate(**kwargs):
    defaults = {
        "title": "Test Song",
        "artist": "Test Artist",
        "artist_mbid": "artist-mbid-1",
        "mbid": "track-mbid-1",
        "duration_ms": 180000,
        "tag_weight_sum": 100,
        "track_tag_score": 0,
        "listen_count": 1000,
        "user_count": 500,
        "artist_listen_count": 0,
        "tags": ["rock"],
    }
    defaults.update(kwargs)
    return Candidate(**defaults)


class TestNormalizeTitle:
    def test_strips_remaster_suffix(self):
        assert normalize_title("Song - Remastered 2011") == "song"
        assert normalize_title("Song (Remastered)") == "song"

    def test_strips_live_suffix(self):
        assert normalize_title("Song (Live)") == "song"
        assert normalize_title("Song [Live at Wembley]") == "song"

    def test_strips_featuring_credits(self):
        assert normalize_title("Song feat. Other Artist") == "song"
        assert normalize_title("Song ft. Other Artist") == "song"
        assert normalize_title("Song featuring Other Artist") == "song"

    def test_strips_part_indicators(self):
        assert normalize_title("Song, Part 2") == "song"
        assert normalize_title("Song, Pt. II") == "song"

    def test_does_not_strip_hyphenated_words_in_title(self):
        assert normalize_title("Drive-In Saturday") == "drive-in saturday"

    def test_lowercases_result(self):
        assert normalize_title("MY SONG") == "my song"


class TestTitlesOverlap:
    def test_returns_true_for_identical_titles(self):
        assert titles_overlap("song", "song") is True

    def test_returns_true_when_longer_title_starts_with_shorter_plus_delimiter(self):
        assert titles_overlap("song - remastered", "song") is True
        assert titles_overlap("song (live)", "song") is True
        assert titles_overlap("song [bonus]", "song") is True

    def test_returns_false_for_unrelated_titles(self):
        assert titles_overlap("song", "other song") is False

    def test_returns_false_when_longer_starts_with_shorter_but_no_delimiter(self):
        # "songwriter" starts with "song" but has no space-delimiter
        assert titles_overlap("songwriter", "song") is False


class TestFilterSeeds:
    seeds = [Seed(mbid="s1", title="Seed Song", artist="Artist A")]

    def test_removes_candidates_whose_title_matches_a_seed(self):
        candidates = [
            make_candidate(title="Seed Song"),
            make_candidate(title="Other Track", mbid="mbid-2"),
        ]
        result = filter_seeds(candidates, self.seeds)
        assert len(result) == 1
        assert result[0].title == "Other Track"

    def test_removes_variant_versions_of_seed_titles(self):
        candidates = [
            make_candidate(title="Seed Song - Remastered"),
            make_candidate(title="Unrelated Track", mbid="mbid-3"),
        ]
        result = filter_seeds(candidates, self.seeds)
        assert len(result) == 1
        assert result[0].title == "Unrelated Track"

    def test_is_case_insensitive_for_title_matching(self):
        candidates = [make_candidate(title="SEED SONG")]
        assert len(filter_seeds(candidates, self.seeds)) == 0

    def test_removes_all_tracks_by_seed_artist(self):
        candidates = [
            make_candidate(title="Seed Song", artist="Artist A"),
            make_candidate(
                title="Other Song by Seed Artist", artist="Artist A", mbid="mbid-2"
            ),
            make_candidate(title="Unrelated Track", artist="Artist B", mbid="mbid-3"),
        ]
        result = filter_seeds(candidates, self.seeds)
        assert len(result) == 1
        assert result[0].title == "Unrelated Track"

    def test_is_case_insensitive_for_artist_matching(self):
        candidates = [
            make_candidate(title="Another Track", artist="artist a", mbid="mbid-2")
        ]
        assert len(filter_seeds(candidates, self.seeds)) == 0

    def test_excludes_all_tracks_by_every_seed_artist_in_multi_seed(self):
        multi_seeds = [
            Seed(mbid="s1", title="Song One", artist="Band One"),
            Seed(mbid="s2", title="Song Two", artist="Band Two"),
        ]
        candidates = [
            make_candidate(title="Track by Band One", artist="Band One"),
            make_candidate(
                title="Track by Band Two", artist="Band Two", mbid="mbid-2"
            ),
            make_candidate(
                title="Track by Other", artist="Band Three", mbid="mbid-3"
            ),
        ]
        result = filter_seeds(candidates, multi_seeds)
        assert len(result) == 1
        assert result[0].artist == "Band Three"

    def test_still_filters_same_title_tracks_from_non_seed_artists(self):
        candidates = [
            make_candidate(
                title="Seed Song", artist="Cover Artist", mbid="mbid-cover"
            ),
            make_candidate(title="Different Track", artist="Cover Artist", mbid="mbid-2"),
        ]
        result = filter_seeds(candidates, self.seeds)
        assert len(result) == 1
        assert result[0].title == "Different Track"

    def test_with_exclude_seed_artists_false_other_tracks_by_seed_artist_are_kept(self):
        candidates = [
            make_candidate(title="Seed Song", artist="Artist A"),
            make_candidate(
                title="Other Song by Seed Artist", artist="Artist A", mbid="mbid-2"
            ),
            make_candidate(
                title="Unrelated Track", artist="Artist B", mbid="mbid-3"
            ),
        ]
        result = filter_seeds(candidates, self.seeds, exclude_seed_artists=False)
        assert len(result) == 2
        titles = [c.title for c in result]
        assert "Other Song by Seed Artist" in titles
        assert "Unrelated Track" in titles
        assert "Seed Song" not in titles


class TestDeduplicateByMbid:
    def test_removes_duplicate_mbids_keeping_first_occurrence(self):
        candidates = [
            make_candidate(title="Song A", mbid="same-mbid", listen_count=100),
            make_candidate(
                title="Song A (Live)", mbid="same-mbid", listen_count=200
            ),
        ]
        result = deduplicate_by_mbid(candidates)
        assert len(result) == 1
        assert result[0].title == "Song A"

    def test_keeps_candidates_with_empty_mbids(self):
        candidates = [
            make_candidate(title="No MBID A", mbid=""),
            make_candidate(title="No MBID B", mbid=""),
        ]
        result = deduplicate_by_mbid(candidates)
        assert len(result) == 2

    def test_does_not_mutate_input_array(self):
        candidates = [
            make_candidate(mbid="a"),
            make_candidate(mbid="a"),
        ]
        original_len = len(candidates)
        deduplicate_by_mbid(candidates)
        assert len(candidates) == original_len


class TestDeduplicateByTitle:
    def test_prefers_candidate_with_mbid_over_one_without(self):
        candidates = [
            make_candidate(title="Song", mbid="", listen_count=9999),
            make_candidate(title="Song - Remastered", mbid="real-mbid", listen_count=1),
        ]
        result = deduplicate_by_title(candidates)
        assert len(result) == 1
        assert result[0].mbid == "real-mbid"

    def test_when_both_have_mbids_keeps_more_listens(self):
        candidates = [
            make_candidate(title="Song", mbid="mbid-a", listen_count=500),
            make_candidate(title="Song (Live)", mbid="mbid-b", listen_count=2000),
        ]
        result = deduplicate_by_title(candidates)
        assert len(result) == 1
        assert result[0].listen_count == 2000

    def test_treats_different_artists_as_different_entries(self):
        candidates = [
            make_candidate(title="Song", artist="Artist A", mbid="a1"),
            make_candidate(title="Song", artist="Artist B", mbid="b1"),
        ]
        assert len(deduplicate_by_title(candidates)) == 2

    def test_does_not_mutate_input_array(self):
        candidates = [
            make_candidate(title="Song", mbid="mbid-1"),
            make_candidate(title="Song (Remastered)", mbid="mbid-2"),
        ]
        original_len = len(candidates)
        deduplicate_by_title(candidates)
        assert len(candidates) == original_len
