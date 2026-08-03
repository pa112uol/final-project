"""
Recommendation evaluation harness.

Mirrors eval.test.ts: recall, MRR, leave-one-out stability, novelty effect, MMR diversity.
Uses a fixed synthetic candidate pool so tests are deterministic and require no network calls.
"""
import pytest
from recommendations.tags import (
    build_tag_weights,
    normalize_tag,
    distinctive_tags_per_seed,
    seeds_matched_by_track,
)
from recommendations.scoring import score_and_sort
from recommendations.diversify import mmr_select, jaccard_sets, tokenize
from recommendations.mood import apply_mood_scores, mood_match_score
from recommendations.types import Candidate, ScoredCandidate, LFTag
from recommendations.utils import get_field


# Fraction of the relevant set that appears in the top k positions
def recall_at_k(ranked: list, relevant: set, k: int) -> float:
    if not relevant:
        return 0
    return sum(1 for c in ranked[:k] if c.mbid in relevant) / len(relevant)


# Reciprocal rank of the first relevant result (0 when none appear)
def mrr(ranked: list, relevant: set) -> float:
    for i, c in enumerate(ranked):
        if c.mbid in relevant:
            return 1 / (i + 1)
    return 0


# Mean pairwise Jaccard distance between tag sets in a list.
# A score of 1 means every pair of results shares no tags
def intralist_diversity(tracks: list) -> float:
    if len(tracks) < 2:
        return 0
    sets = [tokenize(t.tags) for t in tracks]
    total = 0
    pairs = 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            total += 1 - jaccard_sets(sets[i], sets[j])
            pairs += 1
    return total / pairs


# Fraction of the top k that actually express the requested mood. The blunt
# half of the pair: it says whether mood reached the results at all
def mood_precision_at_k(ranked: list, mood: str, k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for c in top if mood_match_score(c.tags, mood) > 0) / len(top)


# Mean mood score across the top k. Rewards how strongly results match rather
# than just whether they do, and goes negative when results actively
# contradict the mood - the count-based metric cannot see either
def mean_mood_score_at_k(ranked: list, mood: str, k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(mood_match_score(c.tags, mood) for c in top) / len(top)


def seed_match_counts(tracks: list, distinctive: list) -> list:
    counts = [0] * len(distinctive)
    for track in tracks:
        for index in seeds_matched_by_track(track.tags, distinctive):
            counts[index] += 1
    return counts


# Fraction of seeds that at least one result reflects. A two-seed query whose
# results all come from one seed's genre scores 0.5 no matter how good they are
def seed_coverage(tracks: list, distinctive: list) -> float:
    if not distinctive:
        return 0.0
    return sum(1 for count in seed_match_counts(tracks, distinctive) if count) / len(
        distinctive
    )


# How evenly the results split across seeds: 1.0 when every seed is reflected by
# equally many tracks, 0.0 when any seed is shut out entirely
def seed_balance(tracks: list, distinctive: list) -> float:
    if not distinctive:
        return 0.0
    counts = seed_match_counts(tracks, distinctive)
    if max(counts) == 0:
        return 0.0
    return min(counts) / max(counts)


def apply_track_tag_scores(candidates: list, tag_weights: dict) -> list:
    nw = {normalize_tag(k.lower()): v for k, v in tag_weights.items()}
    result = []
    for c in candidates:
        score = sum(nw.get(normalize_tag(t.lower()), 0) for t in c.tags)
        result.append(Candidate(
            title=c.title,
            artist=c.artist,
            artist_mbid=c.artist_mbid,
            mbid=c.mbid,
            duration_ms=c.duration_ms,
            tag_weight_sum=c.tag_weight_sum,
            track_tag_score=score,
            listen_count=c.listen_count,
            user_count=c.user_count,
            artist_listen_count=c.artist_listen_count,
            tags=c.tags,
        ))
    return result


# Two shoegaze and dreampop seed tag profiles used across all evaluation sessions
SEED_TAG_SETS = [
    [
        LFTag(name="shoegaze", count=100),
        LFTag(name="dreampop", count=60),
        LFTag(name="noise pop", count=30),
    ],
    [
        LFTag(name="shoegaze", count=90),
        LFTag(name="dreampop", count=50),
        LFTag(name="indie", count=40),
    ],
]

# Four genre matching candidates and three unrelated distractors.
# tag_weight_sum represents expected artist coverage scores from build_candidates
CANDIDATE_POOL = [
    Candidate(title="Alison", artist="Slowdive", artist_mbid="a1", mbid="c1", duration_ms=300000, tag_weight_sum=150, track_tag_score=0, listen_count=50000, user_count=20000, artist_listen_count=0, tags=["shoegaze", "dreampop"]),
    Candidate(title="When the Sun Hits", artist="Slowdive", artist_mbid="a1", mbid="c2", duration_ms=260000, tag_weight_sum=140, track_tag_score=0, listen_count=40000, user_count=15000, artist_listen_count=0, tags=["shoegaze", "noise pop"]),
    Candidate(title="Vapour Trail", artist="Ride", artist_mbid="a2", mbid="c3", duration_ms=240000, tag_weight_sum=130, track_tag_score=0, listen_count=30000, user_count=10000, artist_listen_count=0, tags=["shoegaze", "dreampop"]),
    Candidate(title="Heaven or Las Vegas", artist="Cocteau Twins", artist_mbid="a3", mbid="c4", duration_ms=280000, tag_weight_sum=120, track_tag_score=0, listen_count=25000, user_count=8000, artist_listen_count=0, tags=["dreampop", "shoegaze"]),
    Candidate(title="GOAT", artist="Drake", artist_mbid="a10", mbid="d1", duration_ms=200000, tag_weight_sum=10, track_tag_score=0, listen_count=5000000, user_count=2000000, artist_listen_count=0, tags=["hip hop", "rap", "trap"]),
    Candidate(title="Blinding Lights", artist="The Weeknd", artist_mbid="a11", mbid="d2", duration_ms=200000, tag_weight_sum=10, track_tag_score=0, listen_count=8000000, user_count=3000000, artist_listen_count=0, tags=["pop", "synth pop"]),
    Candidate(title="Country Roads", artist="John Denver", artist_mbid="a12", mbid="d3", duration_ms=200000, tag_weight_sum=5, track_tag_score=0, listen_count=2000000, user_count=800000, artist_listen_count=0, tags=["country", "folk"]),
]

RELEVANT = {"c1", "c2", "c3", "c4"}


# Three tracks per cluster with identical tags and descending final_scores.
# Greedy top 3 picks all of cluster A giving ILD of 0
def make_cluster(prefix: str, tags: list, base_score: float, n: int) -> list:
    return [
        ScoredCandidate(
            title=f"Track {prefix}{i + 1}",
            artist=f"Artist {prefix}",
            artist_mbid=f"art-{prefix}",
            mbid=f"{prefix}{i + 1}",
            duration_ms=None,
            tag_weight_sum=0,
            track_tag_score=0,
            listen_count=0,
            user_count=0,
            artist_listen_count=0,
            tags=tags,
            final_score=base_score - i * 0.05,
            relevance_score=base_score - i * 0.05,
            novelty_score=0.5,
        )
        for i in range(n)
    ]


def ranked_pool(novelty: float) -> list:
    tag_weights = build_tag_weights(SEED_TAG_SETS)
    return score_and_sort(apply_track_tag_scores(CANDIDATE_POOL, tag_weights), novelty)


class TestRecallAndRanking:
    def test_recall_at_4_is_1_at_novelty_0(self):
        ranked = ranked_pool(0)
        assert recall_at_k(ranked, RELEVANT, 4) == 1

    def test_mrr_is_1_at_novelty_0(self):
        ranked = ranked_pool(0)
        assert mrr(ranked, RELEVANT) == 1

    def test_recall_at_4_is_1_at_novelty_1(self):
        # Genre match outweighs listen count advantage of mainstream distractors
        ranked = ranked_pool(1)
        assert recall_at_k(ranked, RELEVANT, 4) == 1


class TestLeaveOneOutStability:
    def test_recall_at_4_remains_1_with_single_seed(self):
        # Simulates a user providing only a single seed rather than two
        tag_weights = build_tag_weights([SEED_TAG_SETS[1]])
        ranked = score_and_sort(apply_track_tag_scores(CANDIDATE_POOL, tag_weights), 0)
        assert recall_at_k(ranked, RELEVANT, 4) == 1


class TestNoveltyParameterEffect:
    POPULAR_RELEVANT = Candidate(
        title="Popular Track", artist="Famous Band", artist_mbid="ap", mbid="pop",
        duration_ms=None, tag_weight_sum=150, track_tag_score=0,
        listen_count=10_000_000, user_count=5_000_000, artist_listen_count=0,
        tags=["shoegaze", "dreampop"],
    )
    OBSCURE_RELEVANT = Candidate(
        title="Obscure Track", artist="Unknown Band", artist_mbid="ao", mbid="obs",
        duration_ms=None, tag_weight_sum=80, track_tag_score=0,
        listen_count=500, user_count=200, artist_listen_count=0,
        tags=["shoegaze", "dreampop"],
    )

    def test_novelty_0_popular_ranks_above_obscure(self):
        tag_weights = build_tag_weights(SEED_TAG_SETS)
        pool = apply_track_tag_scores([self.POPULAR_RELEVANT, self.OBSCURE_RELEVANT], tag_weights)
        assert score_and_sort(pool, 0)[0].mbid == "pop"

    def test_novelty_1_obscure_ranks_above_popular(self):
        tag_weights = build_tag_weights(SEED_TAG_SETS)
        pool = apply_track_tag_scores([self.POPULAR_RELEVANT, self.OBSCURE_RELEVANT], tag_weights)
        assert score_and_sort(pool, 1)[0].mbid == "obs"


class TestMmrDiversity:
    def test_mmr_produces_higher_intralist_diversity_than_greedy(self):
        cluster_a = make_cluster("A", ["shoegaze", "dreampop"], 0.9, 3)
        cluster_b = make_cluster("B", ["post punk", "gothic"], 0.75, 3)
        ranked = sorted(cluster_a + cluster_b, key=lambda x: x.final_score, reverse=True)
        greedy_top3 = ranked[:3]
        mmr_top3 = mmr_select(ranked, 3)
        assert intralist_diversity(mmr_top3) > intralist_diversity(greedy_top3)

    def test_mmr_selects_highest_scoring_candidate_first(self):
        cluster_a = make_cluster("A", ["shoegaze", "dreampop"], 0.9, 3)
        cluster_b = make_cluster("B", ["post punk", "gothic"], 0.75, 3)
        ranked = sorted(cluster_a + cluster_b, key=lambda x: x.final_score, reverse=True)
        assert mmr_select(ranked, 4)[0].mbid == "A1"


# Two seeds that share "rock" but diverge on their distinctive genre tags,
# mirroring the real failure case: a funk seed paired with a grunge seed
FUNK_SEED = [LFTag(name="rock", count=100), LFTag(name="funk", count=40)]
GRUNGE_SEED = [LFTag(name="rock", count=100), LFTag(name="grunge", count=40)]


def make_track(artist: str, tags: list) -> ScoredCandidate:
    return ScoredCandidate(
        title=f"{artist} song", artist=artist, artist_mbid="a", mbid=f"m-{artist}",
        duration_ms=None, tag_weight_sum=1, track_tag_score=1, listen_count=1,
        user_count=1, artist_listen_count=0, tags=tags,
    )


class TestDistinctiveTagsPerSeed:
    def test_drops_tags_shared_by_every_seed(self):
        distinctive = distinctive_tags_per_seed([FUNK_SEED, GRUNGE_SEED])
        assert distinctive == [{"funk"}, {"grunge"}]

    def test_keeps_all_tags_for_a_single_seed(self):
        assert distinctive_tags_per_seed([FUNK_SEED]) == [{"rock", "funk"}]

    def test_returns_empty_for_no_seeds(self):
        assert distinctive_tags_per_seed([]) == []

    def test_ignores_long_tail_tags_outside_each_seed_top_n(self):
        # Only the strongest tags characterise a seed; rare tags no candidate
        # carries would otherwise dominate the "distinctive" set
        seed_a = [LFTag(name="funk", count=90), LFTag(name="bristol sound", count=1)]
        seed_b = [LFTag(name="grunge", count=90), LFTag(name="anxious", count=1)]
        distinctive = distinctive_tags_per_seed([seed_a, seed_b], top_n=1)
        assert distinctive == [{"funk"}, {"grunge"}]


class TestSeedCoverage:
    @pytest.fixture
    def distinctive(self):
        return distinctive_tags_per_seed([FUNK_SEED, GRUNGE_SEED])

    def test_scores_one_when_every_seed_is_represented(self, distinctive):
        tracks = [make_track("A", ["funk"]), make_track("B", ["grunge"])]
        assert seed_coverage(tracks, distinctive) == 1.0

    def test_scores_half_when_one_seed_is_shut_out(self, distinctive):
        # The real regression: a two-seed query collapsing to one seed's genre
        tracks = [make_track("A", ["grunge"]), make_track("B", ["grunge"])]
        assert seed_coverage(tracks, distinctive) == 0.5

    def test_scores_zero_when_results_match_no_seed(self, distinctive):
        assert seed_coverage([make_track("A", ["techno"])], distinctive) == 0.0

    def test_counts_a_track_matching_both_seeds_for_each(self, distinctive):
        tracks = [make_track("A", ["funk", "grunge"])]
        assert seed_coverage(tracks, distinctive) == 1.0


class TestSeedBalance:
    @pytest.fixture
    def distinctive(self):
        return distinctive_tags_per_seed([FUNK_SEED, GRUNGE_SEED])

    def test_scores_one_for_an_even_split(self, distinctive):
        tracks = [make_track("A", ["funk"]), make_track("B", ["grunge"])]
        assert seed_balance(tracks, distinctive) == 1.0

    def test_scores_zero_when_a_seed_gets_nothing(self, distinctive):
        tracks = [make_track("A", ["grunge"]), make_track("B", ["grunge"])]
        assert seed_balance(tracks, distinctive) == 0.0

    def test_penalizes_a_lopsided_split(self, distinctive):
        tracks = [
            make_track("A", ["funk"]),
            make_track("B", ["grunge"]),
            make_track("C", ["grunge"]),
            make_track("D", ["grunge"]),
        ]
        assert seed_balance(tracks, distinctive) == pytest.approx(1 / 3)

    def test_scores_zero_when_nothing_matches(self, distinctive):
        assert seed_balance([make_track("A", ["techno"])], distinctive) == 0.0


# Every candidate carries the same two seed tags, the same artist coverage
# score and the same popularity, so relevance and obscurity tie across the
# whole pool and the mood term is the only thing that can reorder it. The
# third tag is the only variable: two canonical chill words, one weaker
# related word, two mood-neutral genre words, and one that means the opposite.
# None of the third tags appear in SEED_TAG_SETS, so none of them shift
# track_tag_score. Neutral and opposing tracks are listed first because
# score_and_sort's sort is stable: with no mood requested every score ties and
# the pool keeps this order, which is what makes the no-mood baseline 0
def make_mood_candidate(mbid: str, third_tag: str) -> Candidate:
    return Candidate(
        title=f"Track {mbid}", artist=f"Artist {mbid}", artist_mbid=f"a-{mbid}",
        mbid=mbid, duration_ms=None, tag_weight_sum=100, track_tag_score=0,
        listen_count=10000, user_count=5000, artist_listen_count=0,
        tags=["shoegaze", "dreampop", third_tag],
    )


MOOD_CANDIDATE_POOL = [
    make_mood_candidate("neutral-1", "post punk"),
    make_mood_candidate("neutral-2", "gothic"),
    make_mood_candidate("opposing", "aggressive"),
    make_mood_candidate("canonical", "mellow"),
    make_mood_candidate("related-strong", "chillout"),
    make_mood_candidate("related-weak", "downtempo"),
]

def mood_ranked_pool(mood, novelty: float = 0.0) -> list:
    tag_weights = build_tag_weights(SEED_TAG_SETS)
    pool = apply_track_tag_scores(MOOD_CANDIDATE_POOL, tag_weights)
    apply_mood_scores(pool, mood)
    return score_and_sort(pool, novelty)


class TestMoodPrecisionMetric:
    def test_scores_one_when_every_result_matches(self):
        ranked = [make_mood_candidate("m", "chillout")]
        assert mood_precision_at_k(ranked, "chill", 1) == 1.0

    def test_scores_zero_when_no_result_matches(self):
        ranked = [make_mood_candidate("n", "post punk")]
        assert mood_precision_at_k(ranked, "chill", 1) == 0.0

    def test_counts_only_the_top_k(self):
        ranked = [
            make_mood_candidate("a", "chillout"),
            make_mood_candidate("b", "post punk"),
        ]
        assert mood_precision_at_k(ranked, "chill", 1) == 1.0
        assert mood_precision_at_k(ranked, "chill", 2) == 0.5

    def test_k_beyond_the_list_length_uses_what_exists(self):
        ranked = [make_mood_candidate("a", "chillout")]
        assert mood_precision_at_k(ranked, "chill", 50) == 1.0

    def test_empty_ranking_scores_zero(self):
        assert mood_precision_at_k([], "chill", 10) == 0.0

    @pytest.mark.parametrize("mood", [None, "", "banana"])
    def test_unknown_mood_scores_zero(self, mood):
        ranked = [make_mood_candidate("m", "chillout")]
        assert mood_precision_at_k(ranked, mood, 1) == 0.0


class TestMeanMoodScoreMetric:
    def test_grades_a_weak_match_below_a_canonical_one(self):
        strong = [make_mood_candidate("s", "chillout")]
        weak = [make_mood_candidate("w", "downtempo")]
        assert mean_mood_score_at_k(strong, "chill", 1) > mean_mood_score_at_k(
            weak, "chill", 1
        )

    def test_goes_negative_when_results_contradict_the_mood(self):
        opposing = [make_mood_candidate("o", "aggressive")]
        assert mean_mood_score_at_k(opposing, "chill", 1) < 0

    def test_separates_pools_the_count_metric_rates_equally(self):
        # Both score 1.0 on precision; only the graded metric tells them apart
        strong = [make_mood_candidate("s", "chillout")]
        weak = [make_mood_candidate("w", "downtempo")]
        assert mood_precision_at_k(strong, "chill", 1) == mood_precision_at_k(
            weak, "chill", 1
        )
        assert mean_mood_score_at_k(strong, "chill", 1) != mean_mood_score_at_k(
            weak, "chill", 1
        )

    def test_empty_ranking_scores_zero(self):
        assert mean_mood_score_at_k([], "chill", 10) == 0.0


class TestMoodRankingQuality:
    def test_requesting_a_mood_fills_the_top_with_on_mood_tracks(self):
        assert mood_precision_at_k(mood_ranked_pool(None), "chill", 3) == 0.0
        assert mood_precision_at_k(mood_ranked_pool("chill"), "chill", 3) == 1.0

    def test_requesting_a_mood_raises_the_graded_score(self):
        without = mean_mood_score_at_k(mood_ranked_pool(None), "chill", 3)
        with_mood = mean_mood_score_at_k(mood_ranked_pool("chill"), "chill", 3)
        assert with_mood > without

    def test_stronger_mood_evidence_outranks_weaker(self):
        order = [c.mbid for c in mood_ranked_pool("chill")]
        assert order.index("canonical") < order.index("related-weak")
        assert order.index("related-strong") < order.index("related-weak")

    def test_contradicting_track_sinks_to_the_bottom(self):
        assert mood_ranked_pool("chill")[-1].mbid == "opposing"

    @pytest.mark.parametrize("novelty", [0.0, 0.5, 1.0])
    def test_mood_steers_results_at_every_novelty_level(self, novelty):
        # The regression that motivated this metric: the previous mood
        # mechanism reached final_score only through the (1 - novelty)
        # relevance term, so at novelty=1 it reordered nothing at all
        ranked = mood_ranked_pool("chill", novelty)
        assert mood_precision_at_k(ranked, "chill", 3) == 1.0

    @pytest.mark.parametrize("novelty", [0.0, 0.5, 1.0])
    def test_no_mood_leaves_the_ranking_untouched(self, novelty):
        tag_weights = build_tag_weights(SEED_TAG_SETS)
        pool = apply_track_tag_scores(MOOD_CANDIDATE_POOL, tag_weights)
        baseline = score_and_sort(pool, novelty)
        assert [c.mbid for c in mood_ranked_pool(None, novelty)] == [
            c.mbid for c in baseline
        ]

    def test_mood_does_not_pull_in_genre_irrelevant_tracks(self):
        # Mood must not override relevance: a chill-tagged track from an
        # unrelated genre still loses to the on-genre pool
        tag_weights = build_tag_weights(SEED_TAG_SETS)
        intruder = Candidate(
            title="Chill Rap", artist="Nobody", artist_mbid="a-x", mbid="off-genre",
            duration_ms=None, tag_weight_sum=10, track_tag_score=0,
            listen_count=10000, user_count=5000, artist_listen_count=0,
            tags=["hip hop", "trap", "chillout"],
        )
        pool = apply_track_tag_scores(MOOD_CANDIDATE_POOL + [intruder], tag_weights)
        apply_mood_scores(pool, "chill")
        assert score_and_sort(pool, 0)[0].mbid != "off-genre"
