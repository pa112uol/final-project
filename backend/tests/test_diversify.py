import pytest
from recommendations.diversify import tokenize, jaccard_sets, mmr_select
from recommendations.types import ScoredCandidate


def make_scored_candidate(**kwargs):
    defaults = {
        "title": "Track",
        "artist": "Artist",
        "artist_mbid": "artist-mbid",
        "mbid": "track-mbid",
        "duration_ms": None,
        "tag_weight_sum": 100,
        "track_tag_score": 0,
        "listen_count": 0,
        "user_count": 0,
        "artist_listen_count": 0,
        "tags": [],
        "final_score": 0.5,
        "relevance_score": 0.5,
        "novelty_score": 0.5,
    }
    defaults.update(kwargs)
    return ScoredCandidate(**defaults)


class TestTokenize:
    def test_splits_multi_word_tags_into_individual_tokens(self):
        tokens = tokenize(["indie rock", "post punk"])
        assert "indie" in tokens
        assert "rock" in tokens
        assert "post" in tokens
        assert "punk" in tokens

    def test_lowercases_all_tokens(self):
        tokens = tokenize(["Shoegaze", "BRITPOP"])
        assert "shoegaze" in tokens
        assert "britpop" in tokens

    def test_deduplicates_tokens_across_tags(self):
        tokens = tokenize(["indie rock", "indie pop"])
        # "indie" appears twice across tags but should be one token
        indie_count = sum(1 for t in tokens if t == "indie")
        assert indie_count == 1

    def test_returns_empty_set_for_empty_input(self):
        assert tokenize([]) == set()
        assert tokenize([""]) == set()


class TestJaccardSets:
    def test_returns_zero_when_either_set_is_empty(self):
        assert jaccard_sets({"a"}, set()) == 0
        assert jaccard_sets(set(), {"a"}) == 0

    def test_returns_one_for_identical_sets(self):
        s = {"rock", "indie"}
        assert jaccard_sets(s, s) == 1

    def test_returns_zero_for_completely_disjoint_sets(self):
        assert jaccard_sets({"a", "b"}, {"c", "d"}) == 0

    def test_returns_correct_value_for_partial_overlap(self):
        # intersection = {b}, union = {a, b, c, d} => 1/4 = 0.25
        result = jaccard_sets({"a", "b"}, {"b", "c", "d"})
        assert abs(result - 0.25) < 1e-9


class TestMmrSelect:
    def test_returns_at_most_k_candidates(self):
        ranked = [
            make_scored_candidate(mbid=f"mbid-{i}", final_score=1 - i * 0.1)
            for i in range(10)
        ]
        assert len(mmr_select(ranked, 5)) == 5

    def test_returns_all_candidates_when_k_is_greater_than_or_equal_to_ranked_length(self):
        ranked = [
            make_scored_candidate(mbid="a"),
            make_scored_candidate(mbid="b"),
        ]
        assert len(mmr_select(ranked, 10)) == 2

    def test_returns_empty_list_for_empty_input(self):
        assert mmr_select([], 5) == []

    def test_selects_highest_scoring_candidate_first(self):
        ranked = [
            make_scored_candidate(mbid="best", final_score=0.9, tags=["rock"]),
            make_scored_candidate(mbid="second", final_score=0.5, tags=["rock"]),
            make_scored_candidate(mbid="third", final_score=0.1, tags=["rock"]),
        ]
        result = mmr_select(ranked, 3)
        assert result[0].mbid == "best"

    def test_penalizes_candidates_with_similar_tags_to_already_selected_ones(self):
        # "copy" has the same tags as "best" and should be deprioritized vs
        # "diverse". Artists must differ, or same-artist redundancy would
        # dominate and mask the tag comparison under test.
        ranked = [
            make_scored_candidate(
                mbid="best",
                artist="A",
                final_score=0.9,
                tags=["shoegaze", "dreampop"],
            ),
            make_scored_candidate(
                mbid="copy",
                artist="B",
                final_score=0.85,
                tags=["shoegaze", "dreampop"],
            ),
            make_scored_candidate(
                mbid="diverse",
                artist="C",
                final_score=0.8,
                tags=["techno", "electronic"],
            ),
        ]
        result = mmr_select(ranked, 2)
        assert result[0].mbid == "best"
        # The second pick should prefer "diverse" over "copy" due to MMR penalty
        assert result[1].mbid == "diverse"

    def test_penalizes_second_track_by_an_already_selected_artist(self):
        # Same artist is maximally redundant even when the tag strings differ,
        # so the lower-scoring track by a fresh artist should win the slot.
        ranked = [
            make_scored_candidate(
                mbid="best", artist="A", final_score=0.9, tags=["shoegaze"]
            ),
            make_scored_candidate(
                mbid="same-artist", artist="A", final_score=0.85, tags=["techno"]
            ),
            make_scored_candidate(
                mbid="other-artist", artist="B", final_score=0.8, tags=["techno"]
            ),
        ]
        result = mmr_select(ranked, 2)
        assert result[0].mbid == "best"
        assert result[1].mbid == "other-artist"
