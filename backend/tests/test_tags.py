import pytest
from recommendations.tags import (
    normalize_tag,
    merge_tags,
    build_tag_weights,
    is_noise_tag,
    distinctive_tags_per_seed,
    seeds_matched_by_track,
    NOISE_TAGS,
    BROAD_FETCH_TAGS,
    MOOD_TAGS,
)
from recommendations.types import LFTag
from recommendations.constants import LB_SOURCE_WEIGHT, TAG_COUNT_SCALE


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
    def test_normalizes_each_source_against_its_own_maximum(self):
        # LB counts raw votes, LF counts per-track percentages. A tag that
        # tops both sources scores full strength despite counts of 3 vs 100.
        lb_tags = [{"name": "shoegaze", "count": 3}]
        lf_tags = [{"name": "shoegaze", "count": 100}]
        result = merge_tags(lb_tags, lf_tags)
        assert len(result) == 1
        assert result[0].count == pytest.approx(TAG_COUNT_SCALE)

    def test_agreeing_sources_reinforce_rather_than_one_replacing_the_other(self):
        # "shoegaze" tops both sources; "dreamy" is LF-only at the same LF
        # strength as "noisy" is LB-only. Agreement must outrank either alone.
        lb_tags = [{"name": "shoegaze", "count": 10}, {"name": "noisy", "count": 10}]
        lf_tags = [{"name": "shoegaze", "count": 100}, {"name": "dreamy", "count": 100}]
        by_name = {t.name: t.count for t in merge_tags(lb_tags, lf_tags)}
        assert by_name["shoegaze"] > by_name["noisy"]
        assert by_name["shoegaze"] > by_name["dreamy"]
        # LB-only vs LF-only reflect the configured source weighting
        assert by_name["noisy"] == pytest.approx(LB_SOURCE_WEIGHT * TAG_COUNT_SCALE)
        assert by_name["dreamy"] == pytest.approx(
            (1 - LB_SOURCE_WEIGHT) * TAG_COUNT_SCALE
        )

    def test_lf_carries_full_weight_when_lb_returns_nothing(self):
        # ListenBrainz coverage is intermittent. A seed it has no data for must
        # still yield a full-strength profile, or it would contribute
        # systematically weaker tags than its co-seeds when they are pooled.
        lf_tags = [{"name": "shoegaze", "count": 100}, {"name": "dreamy", "count": 50}]
        by_name = {t.name: t.count for t in merge_tags([], lf_tags)}
        assert by_name["shoegaze"] == pytest.approx(TAG_COUNT_SCALE)
        assert by_name["dreamy"] == pytest.approx(TAG_COUNT_SCALE / 2)

    def test_lb_carries_full_weight_when_lf_returns_nothing(self):
        lb_tags = [{"name": "shoegaze", "count": 8}, {"name": "noisy", "count": 4}]
        by_name = {t.name: t.count for t in merge_tags(lb_tags, [])}
        assert by_name["shoegaze"] == pytest.approx(TAG_COUNT_SCALE)
        assert by_name["noisy"] == pytest.approx(TAG_COUNT_SCALE / 2)

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
        # 50/90 of LF's strength, taking LF's (1 - LB_SOURCE_WEIGHT) share
        assert dreamy.count == pytest.approx(
            (50 / 90) * (1 - LB_SOURCE_WEIGHT) * TAG_COUNT_SCALE
        )

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


class TestDistinctiveTagsPerSeed:
    def test_drops_tags_shared_by_every_seed(self):
        funk = [LFTag(name="rock", count=100), LFTag(name="funk", count=40)]
        grunge = [LFTag(name="rock", count=100), LFTag(name="grunge", count=40)]
        assert distinctive_tags_per_seed([funk, grunge]) == [{"funk"}, {"grunge"}]

    def test_keeps_all_tags_for_a_single_seed(self):
        seed = [LFTag(name="rock", count=100), LFTag(name="funk", count=40)]
        assert distinctive_tags_per_seed([seed]) == [{"rock", "funk"}]

    def test_ignores_long_tail_tags_outside_each_seed_top_n(self):
        # Only the strongest tags characterise a seed; a rare tag no candidate
        # carries would otherwise dominate the distinctive set
        a = [LFTag(name="funk", count=90), LFTag(name="bristol sound", count=1)]
        b = [LFTag(name="grunge", count=90), LFTag(name="anxious", count=1)]
        assert distinctive_tags_per_seed([a, b], top_n=1) == [{"funk"}, {"grunge"}]

    def test_returns_empty_for_no_seeds(self):
        assert distinctive_tags_per_seed([]) == []


class TestSeedsMatchedByTrack:
    def test_matches_the_seed_whose_distinctive_tag_it_carries(self):
        distinctive = [{"funk"}, {"grunge"}]
        assert seeds_matched_by_track(["funk", "jam"], distinctive) == {0}

    def test_matches_multiple_seeds_for_a_bridge_track(self):
        distinctive = [{"funk"}, {"grunge"}]
        assert seeds_matched_by_track(["funk", "grunge"], distinctive) == {0, 1}

    def test_matches_nothing_when_no_distinctive_tag_present(self):
        assert seeds_matched_by_track(["techno"], [{"funk"}, {"grunge"}]) == set()

    def test_normalizes_hyphens_before_matching(self):
        assert seeds_matched_by_track(["post-punk"], [{"post punk"}]) == {0}
