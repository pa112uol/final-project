"""
Recommendation evaluation harness.

Mirrors eval.test.ts: recall, MRR, leave-one-out stability, novelty effect, MMR diversity.
Uses a fixed synthetic candidate pool so tests are deterministic and require no network calls.
"""
import pytest
from recommendations.tags import build_tag_weights, normalize_tag
from recommendations.scoring import score_and_sort
from recommendations.diversify import mmr_select, jaccard_sets, tokenize
from recommendations.types import Candidate, ScoredCandidate, LFTag


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
