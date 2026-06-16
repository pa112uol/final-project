import pytest
from recommendations.tags import (
    normalize_tag,
    merge_tags,
    build_tag_weights,
    is_noise_tag,
    NOISE_TAGS,
    BROAD_FETCH_TAGS,
    MOOD_TAGS,
)


class TestNormalizeTag:
    def test_replaces_hyphens_with_spaces(self):
        assert normalize_tag("post-punk") == "post punk"
        assert normalize_tag("indie-rock") == "indie rock"

    def test_leaves_non_hyphen_tags_unchanged(self):
        assert normalize_tag("shoegaze") == "shoegaze"


class TestNoiseTags:
    def test_contains_user_collection_noise(self):
        assert "seen live" in NOISE_TAGS
        assert "favorites" in NOISE_TAGS

    def test_does_not_contain_genre_tags(self):
        assert "shoegaze" not in NOISE_TAGS
        assert "britpop" not in NOISE_TAGS


class TestBroadFetchTags:
    def test_contains_top_level_genres(self):
        assert "rock" in BROAD_FETCH_TAGS
        assert "electronic" in BROAD_FETCH_TAGS
        assert "80s" in BROAD_FETCH_TAGS


class TestMoodTags:
    def test_covers_all_expected_moods(self):
        expected_moods = [
            "happy", "sad", "energetic", "chill",
            "angry", "melancholic", "romantic", "focus",
        ]
        for mood in expected_moods:
            assert mood in MOOD_TAGS
            assert len(MOOD_TAGS[mood]) > 0


class TestIsNoiseTag:
    def test_identifies_numeric_tags(self):
        assert is_noise_tag("-1001740215468") is True
        assert is_noise_tag("1234567890") is True

    def test_identifies_four_digit_year_tags(self):
        assert is_noise_tag("2019") is True
        assert is_noise_tag("1994") is True
        assert is_noise_tag("2000") is True

    def test_identifies_full_decade_tags(self):
        assert is_noise_tag("1990s") is True
        assert is_noise_tag("2010s") is True
        assert is_noise_tag("2020s") is True

    def test_identifies_abbreviated_decade_tags(self):
        assert is_noise_tag("70s") is True
        assert is_noise_tag("80s") is True
        assert is_noise_tag("90s") is True

    def test_does_not_flag_real_genre_tags(self):
        assert is_noise_tag("shoegaze") is False
        assert is_noise_tag("dreampop") is False
        assert is_noise_tag("post-punk") is False
        assert is_noise_tag("808s") is False


class TestMergeTags:
    def test_scales_lb_tags_and_keeps_them_over_lf_duplicates(self):
        lb_tags = [{"name": "shoegaze", "count": 3}]
        lf_tags = [{"name": "shoegaze", "count": 100}]
        result = merge_tags(lb_tags, lf_tags)
        # LB tag with count 3 gets scaled to 3*15=45, not replaced by LF's 100
        assert len(result) == 1
        assert result[0].count == 45

    def test_includes_lf_only_tags_not_present_in_lb(self):
        lb_tags = [{"name": "shoegaze", "count": 2}]
        lf_tags = [
            {"name": "shoegaze", "count": 90},
            {"name": "dreamy", "count": 50},
        ]
        result = merge_tags(lb_tags, lf_tags)
        names = [t.name for t in result]
        assert "dreamy" in names
        dreamy = next(t for t in result if t.name == "dreamy")
        assert dreamy.count == 50

    def test_filters_noise_tags_from_both_sources(self):
        lb_tags = [{"name": "seen live", "count": 5}]
        lf_tags = [{"name": "favorites", "count": 80}]
        assert len(merge_tags(lb_tags, lf_tags)) == 0

    def test_returns_empty_when_both_inputs_are_empty(self):
        assert len(merge_tags([], [])) == 0


class TestBuildTagWeights:
    def test_returns_empty_map_for_empty_input(self):
        assert len(build_tag_weights([])) == 0
        assert len(build_tag_weights([[]])) == 0

    def test_assigns_higher_weight_to_tag_shared_across_more_seeds(self):
        # shoegaze appears in both seeds so it carries full consensus weight
        # britpop appears only once and is down-weighted as an idiosyncratic tag
        seed_tag_sets = [
            [{"name": "shoegaze", "count": 10}, {"name": "britpop", "count": 10}],
            [{"name": "shoegaze", "count": 10}],
        ]
        weights = build_tag_weights(seed_tag_sets)
        assert weights["shoegaze"] > weights["britpop"]

    def test_boosts_tag_that_appears_in_every_seed(self):
        # Both tags have identical total TF of 3. rock wins because it is shared
        # across all seeds while shoegaze appears only once.
        seed_tag_sets = [
            [{"name": "rock", "count": 1}, {"name": "shoegaze", "count": 3}],
            [{"name": "rock", "count": 1}],
            [{"name": "rock", "count": 1}],
        ]
        weights = build_tag_weights(seed_tag_sets)
        assert weights["rock"] > weights["shoegaze"]

    def test_normalizes_hyphen_variants_of_same_tag_to_same_entry(self):
        # "post-punk" and "post punk" should be treated as the same normalized tag
        seed_tag_sets = [
            [{"name": "post-punk", "count": 5}],
            [{"name": "post punk", "count": 5}],
        ]
        weights = build_tag_weights(seed_tag_sets)
        # After normalization both resolve to "post punk"; should result in one entry
        assert len(weights) == 1
