import pytest
from recommendations.diversify import (
    tokenize,
    jaccard_sets,
    mmr_select,
    mmr_select_balanced,
)
from recommendations.constants import (
    SELECTION_FOR_VARIETY,
    SELECTION_TOP_MATCH,
)
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

    def test_returns_all_candidates_when_k_is_greater_than_or_equal_to_ranked_length(
        self,
    ):
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
            make_scored_candidate(
                mbid="second", final_score=0.5, tags=["rock"]
            ),
            make_scored_candidate(mbid="third", final_score=0.1, tags=["rock"]),
        ]
        result = mmr_select(ranked, 3)
        assert result[0].mbid == "best"

    def test_penalizes_candidates_with_similar_tags_to_already_selected_ones(
        self,
    ):
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
                mbid="same-artist",
                artist="A",
                final_score=0.85,
                tags=["techno"],
            ),
            make_scored_candidate(
                mbid="other-artist",
                artist="B",
                final_score=0.8,
                tags=["techno"],
            ),
        ]
        result = mmr_select(ranked, 2)
        assert result[0].mbid == "best"
        assert result[1].mbid == "other-artist"


class TestSelectionReason:
    def test_first_pick_is_always_a_top_match(self):
        ranked = [
            make_scored_candidate(mbid="best", artist="A", final_score=0.9),
            make_scored_candidate(mbid="other", artist="B", final_score=0.5),
        ]
        assert mmr_select(ranked, 2)[0].selection_reason == SELECTION_TOP_MATCH

    def test_marks_for_variety_when_diversity_beats_a_higher_score(self):
        # "diverse" scores below "copy" and only wins its slot because "copy"
        # duplicates the incumbent's tags. This is the case the UI has to
        # explain: a card ranked above one with a visibly better bar
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
        assert result[1].mbid == "diverse"
        assert result[1].selection_reason == SELECTION_FOR_VARIETY

    def test_marks_top_match_when_the_best_scoring_candidate_wins_anyway(self):
        # Every candidate shares tags, so the diversity penalty is uniform and
        # cannot reorder anything- each pick is the remaining score leader
        ranked = [
            make_scored_candidate(
                mbid=f"t{i}",
                artist=f"A{i}",
                final_score=0.9 - i * 0.1,
                tags=["rock"],
            )
            for i in range(4)
        ]
        for scored in mmr_select(ranked, 4):
            assert scored.selection_reason == SELECTION_TOP_MATCH

    def test_ties_on_score_do_not_count_as_variety_picks(self):
        # An equal score would have been a top match, so only a
        # strictly better one left behind means diversity decided the pick
        ranked = [
            make_scored_candidate(
                mbid="a", artist="A", final_score=0.5, tags=["rock"]
            ),
            make_scored_candidate(
                mbid="b", artist="B", final_score=0.5, tags=["jazz"]
            ),
        ]
        for scored in mmr_select(ranked, 2):
            assert scored.selection_reason == SELECTION_TOP_MATCH

    def test_last_pick_with_nothing_left_behind_is_a_top_match(self):
        ranked = [
            make_scored_candidate(
                mbid="a", artist="A", final_score=0.2, tags=["rock"]
            ),
            make_scored_candidate(
                mbid="b", artist="B", final_score=0.9, tags=["rock"]
            ),
        ]
        result = mmr_select(ranked, 2)
        assert result[1].mbid == "a"
        assert result[1].selection_reason == SELECTION_TOP_MATCH

    def test_balanced_selection_also_stamps_a_reason_on_every_pick(self):
        cands = [
            make_scored_candidate(
                mbid=f"a{i}",
                artist=f"A{i}",
                final_score=0.9 - i * 0.05,
                tags=["funk"],
            )
            for i in range(3)
        ] + [
            make_scored_candidate(
                mbid="b0", artist="B", final_score=0.3, tags=["grunge"]
            )
        ]
        mapping = {**{f"a{i}": {0} for i in range(3)}, "b0": {1}}
        result = mmr_select_balanced(
            cands, 4, lambda c: mapping.get(c.mbid, set()), seed_count=2
        )
        assert all(
            c.selection_reason in (SELECTION_TOP_MATCH, SELECTION_FOR_VARIETY)
            for c in result
        )

    def test_balanced_quota_pick_is_not_mislabeled_as_variety(self):
        # "b0" is seated by its seed quota, not by the diversity term. It is
        # the only candidate in its pool, so nothing outscored it there and it
        # must read as a top match rather than claiming a variety boost
        cands = [
            make_scored_candidate(
                mbid=f"a{i}",
                artist=f"A{i}",
                final_score=0.9 - i * 0.05,
                tags=["funk"],
            )
            for i in range(3)
        ] + [
            make_scored_candidate(
                mbid="b0", artist="B", final_score=0.1, tags=["grunge"]
            )
        ]
        mapping = {**{f"a{i}": {0} for i in range(3)}, "b0": {1}}
        result = mmr_select_balanced(
            cands, 2, lambda c: mapping.get(c.mbid, set()), seed_count=2
        )
        seated = next(c for c in result if c.mbid == "b0")
        assert seated.selection_reason == SELECTION_TOP_MATCH


class TestMmrSelectBalanced:
    # seed_ids_of built from a static map keyed by mbid, so tests can assign
    # each candidate to whichever seed(s) they need
    def _seed_ids_of(self, mapping):
        return lambda c: mapping.get(c.mbid, set())

    def test_guarantees_each_seed_a_slot_even_when_one_seed_dominates_scores(
        self,
    ):
        # Seed 0 owns the five highest scores; plain MMR would fill all slots
        # with it. Balanced selection must still seat seed 1.
        seed0 = [
            make_scored_candidate(
                mbid=f"a{i}",
                artist=f"A{i}",
                final_score=0.9 - i * 0.05,
                tags=["funk"],
            )
            for i in range(5)
        ]
        seed1 = make_scored_candidate(
            mbid="b1", artist="B", final_score=0.3, tags=["grunge"]
        )
        mapping = {**{f"a{i}": {0} for i in range(5)}, "b1": {1}}
        result = mmr_select_balanced(
            seed0 + [seed1], 4, self._seed_ids_of(mapping), seed_count=2
        )
        mbids = {c.mbid for c in result}
        assert "b1" in mbids

    def test_splits_slots_evenly_when_both_seeds_have_candidates(self):
        cands = [
            make_scored_candidate(
                mbid=f"a{i}",
                artist=f"A{i}",
                final_score=0.9 - i * 0.05,
                tags=["funk"],
            )
            for i in range(5)
        ] + [
            make_scored_candidate(
                mbid=f"b{i}",
                artist=f"B{i}",
                final_score=0.4 - i * 0.05,
                tags=["grunge"],
            )
            for i in range(5)
        ]
        mapping = {
            **{f"a{i}": {0} for i in range(5)},
            **{f"b{i}": {1} for i in range(5)},
        }
        result = mmr_select_balanced(cands, 4, self._seed_ids_of(mapping), 2)
        from_seed0 = sum(1 for c in result if c.mbid.startswith("a"))
        from_seed1 = sum(1 for c in result if c.mbid.startswith("b"))
        assert from_seed0 == 2 and from_seed1 == 2

    def test_falls_back_to_pooled_mmr_when_a_seed_has_no_candidates(self):
        # Seed 1 unrepresented in the pool; selection should still return k
        # tracks rather than stalling
        cands = [
            make_scored_candidate(
                mbid=f"a{i}",
                artist=f"A{i}",
                final_score=0.9 - i * 0.1,
                tags=["funk"],
            )
            for i in range(4)
        ]
        mapping = {f"a{i}": {0} for i in range(4)}
        result = mmr_select_balanced(cands, 3, self._seed_ids_of(mapping), 2)
        assert len(result) == 3

    def test_single_seed_matches_plain_mmr(self):
        cands = [
            make_scored_candidate(
                mbid=f"m{i}",
                artist=f"A{i}",
                final_score=0.9 - i * 0.1,
                tags=["funk"],
            )
            for i in range(5)
        ]
        balanced = mmr_select_balanced(cands, 3, lambda c: {0}, seed_count=1)
        plain = mmr_select(cands, 3)
        assert [c.mbid for c in balanced] == [c.mbid for c in plain]

    def test_returns_empty_for_empty_input(self):
        assert mmr_select_balanced([], 5, lambda c: set(), 2) == []
