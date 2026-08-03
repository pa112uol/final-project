import pytest

from recommendations.constants import MOOD_CONFLICT_PENALTY
from recommendations.mood import (
    MOOD_CONFLICT_VOCABULARY,
    MOOD_RELATED,
    MOOD_VOCABULARY,
    apply_mood_scores,
    is_known_mood,
    mood_match_score,
    normalize_for_match,
)
from recommendations.tags import MOOD_TAGS
from recommendations.types import Candidate


def make_candidate(tags, **overrides):
    defaults = {
        "title": "Track",
        "artist": "Artist",
        "artist_mbid": "a1",
        "mbid": "c1",
        "duration_ms": None,
        "tag_weight_sum": 100.0,
        "track_tag_score": 0.5,
        "listen_count": 1000,
        "user_count": 100,
        "artist_listen_count": 0,
        "tags": tags,
    }
    defaults.update(overrides)
    return Candidate(**defaults)


class TestNormalizeForMatch:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("chill", "chill"),
            ("Chill", "chill"),
            ("trip-hop", "trip hop"),
            ("-melancholic-", "melancholic"),
            ("  feel  good  ", "feel good"),
            ("FEEL-GOOD", "feel good"),
            ("", ""),
        ],
    )
    def test_normalizes_case_hyphens_and_whitespace(self, raw, expected):
        assert normalize_for_match(raw) == expected


class TestVocabularies:
    def test_every_mood_has_a_vocabulary(self):
        assert set(MOOD_VOCABULARY) == set(MOOD_TAGS)
        for mood, vocabulary in MOOD_VOCABULARY.items():
            assert vocabulary, f"{mood} has an empty vocabulary"

    def test_canonical_mood_tags_always_score_full_weight(self):
        for mood, tags in MOOD_TAGS.items():
            for tag in tags:
                assert MOOD_VOCABULARY[mood][normalize_for_match(tag)] == 1.0

    def test_related_terms_do_not_redefine_canonical_ones(self):
        # A related entry must never silently downgrade a MOOD_TAGS term
        for mood, related in MOOD_RELATED.items():
            canonical = {normalize_for_match(t) for t in MOOD_TAGS[mood]}
            overlap = canonical & {normalize_for_match(t) for t in related}
            for tag in overlap:
                assert MOOD_VOCABULARY[mood][tag] == 1.0

    def test_related_weights_are_within_unit_range(self):
        for related in MOOD_RELATED.values():
            assert all(0 < weight <= 1.0 for weight in related.values())

    def test_conflict_vocabulary_never_contradicts_own_vocabulary(self):
        # A tag that signals the requested mood cannot also count against it
        for mood in MOOD_TAGS:
            overlap = set(MOOD_CONFLICT_VOCABULARY[mood]) & set(
                MOOD_VOCABULARY[mood]
            )
            assert overlap == set(), f"{mood} conflicts with itself: {overlap}"


class TestIsKnownMood:
    @pytest.mark.parametrize("mood", list(MOOD_TAGS))
    def test_accepts_every_supported_mood(self, mood):
        assert is_known_mood(mood) is True

    @pytest.mark.parametrize("mood", [None, "", "banana", "HAPPY"])
    def test_rejects_unsupported_values(self, mood):
        assert is_known_mood(mood) is False


class TestMoodMatchScore:
    def test_canonical_tag_scores_full(self):
        assert mood_match_score(["chill"], "chill") == 1.0

    def test_related_tag_scores_below_canonical(self):
        assert 0 < mood_match_score(["downtempo"], "chill") < 1.0

    def test_chillout_matches_chill(self):
        # The single highest-value fix: "chillout" dominates real pools and
        # the previous exact-equality matcher could not see it at all
        assert mood_match_score(["chillout"], "chill") == 1.0

    def test_hyphen_wrapped_tag_matches(self):
        assert mood_match_score(["-melancholic-"], "melancholic") == 1.0

    def test_takes_the_strongest_matching_tag(self):
        assert mood_match_score(["downtempo", "chill"], "chill") == 1.0

    def test_unmatched_tags_score_zero(self):
        assert mood_match_score(["shoegaze", "noise pop"], "chill") == 0.0

    def test_conflicting_tag_scores_negative(self):
        assert mood_match_score(["aggressive"], "chill") == pytest.approx(
            -MOOD_CONFLICT_PENALTY
        )

    def test_match_outweighs_a_single_conflict(self):
        score = mood_match_score(["chill", "aggressive"], "chill")
        assert score == pytest.approx(1.0 - MOOD_CONFLICT_PENALTY)
        assert score > 0

    @pytest.mark.parametrize("tags", [[], None])
    def test_empty_tags_score_zero(self, tags):
        assert mood_match_score(tags, "chill") == 0.0

    @pytest.mark.parametrize("mood", [None, "", "banana"])
    def test_unknown_mood_scores_zero(self, mood):
        assert mood_match_score(["chill"], mood) == 0.0

    @pytest.mark.parametrize("mood", list(MOOD_TAGS))
    def test_score_always_within_bounds(self, mood):
        tags = ["chill", "aggressive", "happy", "sad", "shoegaze", "workout"]
        assert -1.0 <= mood_match_score(tags, mood) <= 1.0


class TestApplyMoodScores:
    def test_writes_scores_onto_candidates(self):
        matching = make_candidate(["chillout"])
        neutral = make_candidate(["shoegaze"])
        apply_mood_scores([matching, neutral], "chill")
        assert matching.mood_score == 1.0
        assert neutral.mood_score == 0.0

    def test_demotes_candidates_carrying_an_opposing_mood(self):
        opposing = make_candidate(["aggressive"])
        apply_mood_scores([opposing], "chill")
        assert opposing.mood_score < 0

    @pytest.mark.parametrize("mood", [None, "", "banana"])
    def test_leaves_candidates_untouched_without_a_valid_mood(self, mood):
        candidate = make_candidate(["chill"])
        apply_mood_scores([candidate], mood)
        assert candidate.mood_score == 0.0

    def test_handles_an_empty_candidate_list(self):
        apply_mood_scores([], "chill")

    def test_works_on_dict_shaped_candidates(self):
        # get_field/set_field support dicts, and the pipeline's client stubs
        # hand dicts through in places
        candidate = {"tags": ["chill"]}
        apply_mood_scores([candidate], "chill")
        assert candidate["mood_score"] == 1.0

    def test_logs_a_warning_when_no_candidate_expresses_the_mood(self, caplog):
        with caplog.at_level("WARNING"):
            apply_mood_scores([make_candidate(["shoegaze"])], "chill")
        assert "matched none" in caplog.text

    def test_warns_when_candidates_only_oppose_the_mood(self, caplog):
        # Demoting opposing tracks is not the same as finding matching ones;
        # the request is still effectively inert and the user should see that
        with caplog.at_level("WARNING"):
            apply_mood_scores(
                [make_candidate(["aggressive"]), make_candidate(["shoegaze"])],
                "chill",
            )
        assert "matched none" in caplog.text

    def test_notes_when_every_candidate_matches(self, caplog):
        with caplog.at_level("INFO"):
            apply_mood_scores(
                [make_candidate(["chillout"]), make_candidate(["mellow"])],
                "chill",
            )
        assert "matched all" in caplog.text
