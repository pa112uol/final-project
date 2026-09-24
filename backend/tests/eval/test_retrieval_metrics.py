import math

import pytest

from recommendations.types import LFTag
from evaluation.playlist_catalogue import PlaylistTrack
from evaluation.retrieval_metrics import (
    RankScores,
    artist_concentration,
    build_relevance,
    fold_artist_name,
    fold_name,
    relevance_key,
    matched_ids,
    mean_defined,
    paired_difference,
    rank_scores,
    recall,
    seed_balance,
    seed_counts,
    title_key,
)


def candidate(title, artist, mbid="", artist_mbid="", tags=None, **extra):
    return {
        "title": title,
        "artist": artist,
        "mbid": mbid,
        "artist_mbid": artist_mbid,
        "tags": tags or [],
        **extra,
    }


@pytest.fixture
def relevance():
    return build_relevance(
        (
            PlaylistTrack("rec-1", "Alison", "Slowdive", ("slowdive-mbid",)),
            PlaylistTrack("rec-2", "Vapour Trail", "Ride", ("ride-mbid",)),
            PlaylistTrack("rec-3", "Dagger", "Slowdive", ("slowdive-mbid",)),
        )
    )


class TestTitleKey:
    @pytest.mark.parametrize(
        "title",
        ["Alison", "alison", "Alison - 2005 Remaster", "Alison (Live)"],
    )
    def test_collapses_title_variants(self, title):
        assert title_key("Slowdive", title) == ("slowdive", "alison")

    def test_ignores_artist_punctuation(self):
        assert title_key("AC/DC", "x")[0] == title_key("ac dc", "x")[0]


class TestRelevanceFolding:
    @pytest.mark.parametrize(
        "left, right",
        [
            ("Beyonc\u00e9", "Beyonce"),
            ("Sigur R\u00f3s", "Sigur Ros"),
            ("M\u00f6tley Cr\u00fce", "Motley Crue"),
            ("The Weeknd", "Weeknd"),
            ("THE Beatles", "beatles"),
            ("Simon & Garfunkel", "Simon and Garfunkel"),
        ],
    )
    def test_artist_variants_fold_together(self, left, right):
        assert fold_artist_name(left) == fold_artist_name(right)

    @pytest.mark.parametrize(
        "left, right",
        [("Radiohead", "Radio"), ("Theory of a Deadman", "Ory of a Deadman")],
    )
    def test_distinct_artists_stay_apart(self, left, right):
        assert fold_artist_name(left) != fold_artist_name(right)

    def test_article_is_only_dropped_as_a_whole_leading_word(self):
        assert fold_artist_name("Them Crooked Vultures") == "them crooked vultures"

    def test_titles_keep_their_leading_article(self):
        assert relevance_key("X", "The Scientist") != relevance_key("X", "Scientist")

    def test_title_accents_fold(self):
        assert fold_name("Caf\u00e9 del Mar") == fold_name("Cafe del Mar")

    def test_accented_candidate_matches_plain_held_out_track(self):
        relevance = build_relevance((PlaylistTrack("", "Halo", "Beyonce", ()),))
        match = candidate("Halo - Remastered", "Beyonc\u00e9")
        assert relevance.track_id(match) == 0
        assert relevance.artist_id(candidate("x", "Beyonc\u00e9")) == 0


class TestRelevanceSet:
    def test_counts_tracks_and_distinct_artists(self, relevance):
        assert relevance.track_count == 3
        assert relevance.artist_count == 2

    def test_matches_track_by_recording_mbid(self, relevance):
        assert relevance.track_id(candidate("Other", "Other", mbid="rec-2")) == 1

    def test_falls_back_to_title_when_mbid_is_stale(self, relevance):
        stale = candidate("Alison (Remastered)", "Slowdive", mbid="stale")
        assert relevance.track_id(stale) == 0

    def test_empty_ids_never_match(self):
        relevance = build_relevance(
            (PlaylistTrack("", "Song", "Band", (), "spotify:track:1"),)
        )
        assert relevance.track_id(candidate("Other", "Other", mbid="")) is None
        assert relevance.artist_id(candidate("x", "Other", artist_mbid="")) is None

    def test_unrelated_track_does_not_match(self, relevance):
        assert relevance.track_id(candidate("When the Sun Hits", "Slowdive")) is None

    def test_matches_artist_by_mbid_then_name(self, relevance):
        assert relevance.artist_id(candidate("x", "Renamed", artist_mbid="ride-mbid")) == 1
        assert relevance.artist_id(candidate("x", "slowdive")) == 0
        assert relevance.artist_id(candidate("x", "Nobody")) is None


class TestRecall:
    def test_counts_distinct_matches(self, relevance):
        pool = [
            candidate("Alison", "Slowdive"),
            candidate("Alison - Remaster", "Slowdive"),
            candidate("Vapour Trail", "Ride"),
        ]
        found = matched_ids(pool, relevance.track_id)
        assert recall(found, relevance.track_count) == pytest.approx(2 / 3)

    def test_empty_relevant_set_gives_zero(self):
        assert recall(set(), 0) == 0.0


class TestRankScores:
    def _id_of(self, item):
        return item

    def test_perfect_ranking(self):
        scores = rank_scores([1, 2, None], {1, 2}, self._id_of, k=3)
        assert scores == RankScores(precision=2 / 3, recall=1.0, ndcg=1.0)

    def test_late_hit_lowers_ndcg(self):
        scores = rank_scores([None, None, 1], {1}, self._id_of, k=3)
        assert scores.recall == 1.0
        assert scores.ndcg == pytest.approx(1 / math.log2(4))

    def test_repeated_hit_counts_once(self):
        scores = rank_scores([1, 1], {1, 2}, self._id_of, k=2)
        assert scores.precision == 0.5
        assert scores.recall == 0.5

    def test_hit_outside_rankable_pool_is_ignored(self):
        assert rank_scores([3], {1}, self._id_of, k=1).precision == 0.0

    def test_nothing_rankable_leaves_ranking_metrics_undefined(self):
        scores = rank_scores([None], set(), self._id_of, k=10)
        assert scores == RankScores(precision=0.0, recall=None, ndcg=None)

    def test_short_list_is_divided_by_k(self):
        assert rank_scores([1], {1}, self._id_of, k=10).precision == 0.1


class TestArtistConcentration:
    def test_counts_artists_by_mbid_or_name(self):
        selected = [
            candidate("a", "A", artist_mbid="a-mbid"),
            candidate("b", "A (alias)", artist_mbid="a-mbid"),
            candidate("c", "B"),
            candidate("d", "b"),
        ]
        result = artist_concentration(selected)
        assert result.unique_artists == 2
        assert result.max_artist_share == 0.5

    def test_empty_list(self):
        result = artist_concentration([])
        assert (result.unique_artists, result.max_artist_share) == (0, 0.0)


class TestSeedBalance:
    @pytest.fixture
    def seed_tags(self):
        return [
            [LFTag("shoegaze", 100), LFTag("rock", 50)],
            [LFTag("jazz", 100), LFTag("rock", 50)],
        ]

    def test_counts_tracks_per_seed_on_distinctive_tags(self, seed_tags):
        selected = [
            candidate("a", "A", tags=["shoegaze"]),
            candidate("b", "B", tags=["shoegaze", "jazz"]),
            candidate("c", "C", tags=["rock"]),
        ]
        assert seed_counts(selected, seed_tags) == [2, 1]

    @pytest.mark.parametrize(
        "counts, coverage, balance, shortfall",
        [
            ([5, 5], 1.0, 1.0, False),
            ([8, 2], 1.0, 0.25, True),
            ([10, 0], 0.5, 0.0, True),
            ([0, 0], 0.0, 0.0, True),
        ],
    )
    def test_coverage_balance_and_shortfall(self, counts, coverage, balance, shortfall):
        result = seed_balance(counts, k=10)
        assert result.coverage == coverage
        assert result.balance == balance
        assert result.quota_shortfall is shortfall

    def test_undefined_for_one_seed(self):
        assert seed_balance([10], k=10) is None


class TestMeanDefined:
    def test_ignores_undefined_values(self):
        assert mean_defined([1.0, None, 3.0]) == 2.0

    def test_all_undefined_gives_none(self):
        assert mean_defined([None, None]) is None


class TestPairedDifference:
    def test_consistent_improvement_excludes_zero(self):
        result = paired_difference([1.0, 1.1, 0.9, 1.2], [0.0, 0.1, 0.0, 0.1])
        assert result.mean == pytest.approx(1.0)
        assert result.low <= result.mean <= result.high
        assert result.excludes_zero

    def test_mixed_signs_straddle_zero(self):
        result = paired_difference([1.0, 0.0, 1.0, 0.0], [0.0, 1.0, 0.0, 1.0])
        assert not result.excludes_zero

    def test_drops_pairs_with_an_undefined_side(self):
        result = paired_difference([1.0, None, 2.0], [0.0, 1.0, None])
        assert result.pairs == 1

    def test_all_pairs_undefined_gives_none(self):
        assert paired_difference([None], [1.0]) is None

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            paired_difference([1.0], [1.0, 2.0])

    def test_is_reproducible(self):
        args = ([0.3, 0.1, 0.5, 0.2], [0.1, 0.2, 0.1, 0.1])
        assert paired_difference(*args) == paired_difference(*args)
