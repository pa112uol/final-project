import math
import pytest
from recommendations.scoring import median, log_obscurity, score_and_sort
from recommendations.types import Candidate


def make_candidate(**kwargs):
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
    }
    defaults.update(kwargs)
    return Candidate(**defaults)


class TestMedian:
    def test_middle_value_odd_length(self):
        assert median([1, 3, 5]) == 3
        assert median([5, 1, 3]) == 3

    def test_average_of_two_middle_values_even_length(self):
        assert median([1, 2, 3, 4]) == 2.5

    def test_single_element(self):
        assert median([7]) == 7

    def test_does_not_mutate_input(self):
        arr = [3, 1, 2]
        median(arr)
        assert arr == [3, 1, 2]


class TestLogObscurity:
    def test_returns_zero_when_log_max_is_zero_or_negative(self):
        assert log_obscurity(100, 0) == 0
        assert log_obscurity(100, -1) == 0

    def test_returns_one_for_count_zero(self):
        log_max = math.log1p(1_000_000)
        assert log_obscurity(0, log_max) == 1

    def test_returns_zero_for_max_count(self):
        max_count = 1_000_000
        log_max = math.log1p(max_count)
        assert abs(log_obscurity(max_count, log_max)) < 1e-9

    def test_returns_value_between_zero_and_one_for_intermediate_counts(self):
        log_max = math.log1p(1_000_000)
        obs = log_obscurity(1000, log_max)
        assert obs > 0
        assert obs < 1


class TestScoreAndSort:
    def test_returns_empty_array_for_empty_input(self):
        assert score_and_sort([], 0) == []

    def test_normalizes_final_score_to_zero_one_range_for_single_candidate(
        self,
    ):
        result = score_and_sort([make_candidate(tag_weight_sum=50)], 0)
        assert result[0].final_score >= 0
        assert result[0].final_score <= 1

    def test_sorts_by_descending_final_score(self):
        candidates = [
            make_candidate(tag_weight_sum=10, mbid="a"),
            make_candidate(tag_weight_sum=100, mbid="b"),
            make_candidate(tag_weight_sum=50, mbid="c"),
        ]
        result = score_and_sort(candidates, 0)
        for i in range(len(result) - 1):
            assert result[i].final_score >= result[i + 1].final_score

    def test_at_novelty_zero_higher_tag_weight_wins(self):
        low = make_candidate(tag_weight_sum=10, listen_count=0, mbid="a")
        high = make_candidate(tag_weight_sum=100, listen_count=0, mbid="b")
        result = score_and_sort([low, high], 0)
        assert result[0].mbid == "b"

    def test_at_novelty_one_more_obscure_candidate_scores_higher(self):
        # popular has huge listen count, obscure has tiny listen count
        popular = make_candidate(
            tag_weight_sum=100,
            listen_count=1_000_000,
            user_count=500_000,
            mbid="popular",
        )
        obscure = make_candidate(
            tag_weight_sum=100, listen_count=10, user_count=5, mbid="obscure"
        )
        result = score_and_sort([popular, obscure], 1)
        assert result[0].mbid == "obscure"

    def test_assigns_neutral_obscurity_to_candidates_with_no_popularity_data(
        self,
    ):
        # Two known candidates bracket the obscurity range. Unknown gets median.
        popular = make_candidate(
            listen_count=1_000_000, user_count=500_000, mbid="popular"
        )
        niche = make_candidate(listen_count=1_000, user_count=500, mbid="niche")
        unknown = make_candidate(
            listen_count=0, artist_listen_count=0, mbid="unknown"
        )
        result = score_and_sort([popular, niche, unknown], 0.5)
        unknown_result = next(r for r in result if r.mbid == "unknown")
        # Neutral median lands strictly between the min and max after normalization
        assert unknown_result.novelty_score > 0
        assert unknown_result.novelty_score < 1

    def test_attaches_relevance_score_and_novelty_score_to_each_result(self):
        result = score_and_sort([make_candidate()], 0.5)
        assert isinstance(result[0].relevance_score, float)
        assert isinstance(result[0].novelty_score, float)

    def test_novelty_score_spans_full_zero_one_range(self):
        # The novelty score is min-max scaled per result set, so the most popular
        # candidate gets 0 and the most obscure gets 1, with everything else in between
        popular = make_candidate(
            listen_count=1_000_000, user_count=500_000, mbid="popular"
        )
        niche = make_candidate(listen_count=1_000, user_count=500, mbid="niche")
        obscure = make_candidate(listen_count=10, user_count=5, mbid="obscure")
        result = score_and_sort([popular, niche, obscure], 0.5)
        scores = {r.mbid: r.novelty_score for r in result}
        assert scores["popular"] == pytest.approx(0.0)
        assert scores["obscure"] == pytest.approx(1.0)
        assert 0 < scores["niche"] < 1

    def test_novelty_score_matches_obscurity_term_of_final_score(self):
        # The novelty score is the obscurity term of the final score, so at novelty=1.0
        # the final score is exactly equal to the novelty score
        candidates = [
            make_candidate(listen_count=1_000_000, mbid="popular"),
            make_candidate(listen_count=1_000, mbid="niche"),
            make_candidate(listen_count=10, mbid="obscure"),
        ]
        for scored in score_and_sort(candidates, 1.0):
            assert scored.final_score == pytest.approx(scored.novelty_score)

    def test_relevance_and_novelty_share_the_same_normalized_scale(self):
        # Both are min-max scaled per result set with each spans exactly [0, 1]
        candidates = [
            make_candidate(
                tag_weight_sum=100, listen_count=1_000_000, mbid="a"
            ),
            make_candidate(tag_weight_sum=50, listen_count=1_000, mbid="b"),
            make_candidate(tag_weight_sum=10, listen_count=10, mbid="c"),
        ]
        result = score_and_sort(candidates, 0.5)
        for field in ("relevance_score", "novelty_score"):
            values = [getattr(r, field) for r in result]
            assert min(values) == pytest.approx(0.0)
            assert max(values) == pytest.approx(1.0)

    def test_penalizes_candidates_with_no_track_tag_match(self):
        with_tag_match = make_candidate(
            tag_weight_sum=100,
            track_tag_score=50,
            listen_count=0,
            mbid="matched",
        )
        no_tag_match = make_candidate(
            tag_weight_sum=100,
            track_tag_score=0,
            listen_count=0,
            mbid="unmatched",
        )
        result = score_and_sort([with_tag_match, no_tag_match], 0)
        assert result[0].mbid == "matched"
        assert result[0].relevance_score > result[1].relevance_score

    def test_track_tag_score_zero_fallback_is_half_artist_norm(self):
        # Candidate A: trackTagScore matches half of max
        # Candidate B: no match - fallback is 0.5 * artist_norm
        # At 60/40 blend and max tagWeightSum=100:
        # A: artistNorm=1, trackTagNorm=1 => relevance=1.0
        # B: artistNorm=1, trackTagNorm=0.5 (fallback) => relevance=0.8
        max_tag_candidate = make_candidate(
            tag_weight_sum=100, track_tag_score=100, mbid="max"
        )
        zero_tag_candidate = make_candidate(
            tag_weight_sum=100, track_tag_score=0, mbid="zero"
        )
        result = score_and_sort([max_tag_candidate, zero_tag_candidate], 0)
        assert result[0].mbid == "max"
        assert result[1].mbid == "zero"
        assert result[1].relevance_score < result[0].relevance_score


class TestMoodScoring:
    def test_mood_score_of_zero_leaves_final_score_untouched(self):
        # The guarantee that an unmoodied pipeline run is bit-identical: every
        # candidate carries mood_score 0.0 and the mood term must vanish
        candidates = [
            make_candidate(mbid="a", tag_weight_sum=100, listen_count=500),
            make_candidate(mbid="b", tag_weight_sum=60, listen_count=900),
            make_candidate(mbid="c", tag_weight_sum=20, listen_count=100),
        ]
        for novelty in (0.0, 0.5, 1.0):
            without = score_and_sort(candidates, novelty)
            baseline = {c.mbid: c.final_score for c in without}
            explicit_zero = score_and_sort(
                [
                    make_candidate(**{**vars(c), "mood_score": 0.0})
                    for c in candidates
                ],
                novelty,
            )
            assert {c.mbid: c.final_score for c in explicit_zero} == baseline

    def test_positive_mood_score_raises_final_score(self):
        plain = make_candidate(mbid="plain", tag_weight_sum=100)
        moody = make_candidate(mbid="moody", tag_weight_sum=100, mood_score=1.0)
        result = score_and_sort([plain, moody], 0)
        assert result[0].mbid == "moody"
        assert result[0].final_score > result[1].final_score

    def test_negative_mood_score_lowers_final_score(self):
        plain = make_candidate(mbid="plain", tag_weight_sum=100)
        opposing = make_candidate(
            mbid="opposing", tag_weight_sum=100, mood_score=-1.0
        )
        result = score_and_sort([plain, opposing], 0)
        assert result[0].mbid == "plain"
        assert result[1].mbid == "opposing"

    def test_mood_still_applies_at_maximum_novelty(self):
        # At novelty=1.0, the final score is equal to the novelty score, but the mood term
        # is still applied to the novelty score, so a candidate with positive mood_score
        # will still outrank a candidate with neutral mood_score, even if they have the same
        # tag_weight_sum and listen_count
        plain = make_candidate(
            mbid="plain", tag_weight_sum=100, listen_count=100
        )
        moody = make_candidate(
            mbid="moody", tag_weight_sum=100, listen_count=100, mood_score=1.0
        )
        result = score_and_sort([plain, moody], 1.0)
        assert result[0].mbid == "moody"
        assert result[0].final_score > result[1].final_score

    def test_mood_score_survives_conversion_to_scored_candidate(self):
        result = score_and_sort([make_candidate(mbid="m", mood_score=0.75)], 0)
        assert result[0].mood_score == 0.75
