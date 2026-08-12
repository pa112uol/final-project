import math
import random

from recommendations.tags import build_tag_weights
from recommendations.scoring import score_and_sort
from recommendations.diversify import mmr_select
from recommendations.pipeline import apply_artist_cap, apply_tag_floor
from recommendations.constants import MAX_TRACKS_PER_ARTIST
from recommendations.types import Candidate
from backend.tests.eval.test_eval import (
    SEED_TAG_SETS,
    apply_track_tag_scores,
    intralist_diversity,
    recall_at_k,
)

FINAL_K = 10
CATALOGUE_SEED = 7
RANDOM_BASELINE_SEED = 11
RANDOM_BASELINE_TRIALS = 200
NOVELTY_SWEEP = [0.0, 0.25, 0.5, 0.75, 1.0]

ON_GENRE_ARTISTS = 4
TRACKS_PER_ON_GENRE_ARTIST = 4
ADJACENT_TRACKS = 8
DISTRACTOR_TRACKS = 8

ON_GENRE_TAGS = [
    ["shoegaze", "dreampop"],
    ["shoegaze", "noise pop"],
    ["dreampop", "ethereal"],
    ["shoegaze", "dreampop", "slowcore"],
]

ADJACENT_TAGS = ["indie", "post punk"]
DISTRACTOR_TAGS = [
    ["pop", "dance"],
    ["hip hop", "trap"],
    ["country", "folk"],
    ["edm", "house"],
]


def make_candidate(
    title: str,
    artist: str,
    mbid: str,
    tag_weight_sum: int,
    listen_count: int,
    tags: list,
) -> Candidate:
    return Candidate(
        title=title,
        artist=artist,
        artist_mbid=f"artist-{artist}",
        mbid=mbid,
        duration_ms=None,
        tag_weight_sum=tag_weight_sum,
        track_tag_score=0,
        listen_count=listen_count,
        user_count=listen_count // 3,
        artist_listen_count=0,
        tags=tags,
    )


def log_uniform_listens(
    rng: random.Random, low_exp: float, high_exp: float
) -> int:
    return int(10 ** rng.uniform(low_exp, high_exp))


def build_catalogue() -> list:
    rng = random.Random(CATALOGUE_SEED)
    pool = []
    for a in range(ON_GENRE_ARTISTS):
        for t in range(TRACKS_PER_ON_GENRE_ARTIST):
            pool.append(
                make_candidate(
                    title=f"On-Genre {a + 1}-{t + 1}",
                    artist=f"Genre Artist {a + 1}",
                    mbid=f"g{a + 1}-{t + 1}",
                    tag_weight_sum=150 - 10 * a,
                    listen_count=log_uniform_listens(rng, 3.0, 5.3),
                    tags=ON_GENRE_TAGS[t % len(ON_GENRE_TAGS)],
                )
            )
    for j in range(ADJACENT_TRACKS):
        pool.append(
            make_candidate(
                title=f"Adjacent {j + 1}",
                artist=f"Adjacent Artist {j + 1}",
                mbid=f"adj{j + 1}",
                tag_weight_sum=60 - 2 * j,
                listen_count=log_uniform_listens(rng, 4.7, 5.9),
                tags=ADJACENT_TAGS,
            )
        )
    for j in range(DISTRACTOR_TRACKS):
        pool.append(
            make_candidate(
                title=f"Distractor {j + 1}",
                artist=f"Mainstream Artist {j + 1}",
                mbid=f"dis{j + 1}",
                tag_weight_sum=12 - j,
                listen_count=log_uniform_listens(rng, 6.3, 6.95),
                tags=DISTRACTOR_TAGS[j % len(DISTRACTOR_TAGS)],
            )
        )
    return pool


CATALOGUE = build_catalogue()
RELEVANT = {c.mbid for c in CATALOGUE if c.mbid.startswith("g")}
TOTAL_LISTENS = sum(c.listen_count for c in CATALOGUE)


def dcg(gains: list) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked: list, relevant: set, k: int) -> float:
    if not relevant:
        return 0.0
    gains = [1.0 if c.mbid in relevant else 0.0 for c in ranked[:k]]
    ideal = [1.0] * min(k, len(relevant))
    return dcg(gains) / dcg(ideal)


def mean_self_information_at_k(
    ranked: list, total_listens: int, k: int
) -> float:
    top = ranked[:k]
    if not top or total_listens <= 0:
        return 0.0
    return sum(
        -math.log2(max(c.listen_count, 1) / total_listens) for c in top
    ) / len(top)


def unique_artists(tracks: list) -> int:
    return len({c.artist.lower() for c in tracks})


def ranked_catalogue(novelty: float) -> list:
    tag_weights = build_tag_weights(SEED_TAG_SETS)
    return score_and_sort(
        apply_track_tag_scores(CATALOGUE, tag_weights), novelty
    )


def popularity_ranking(pool: list) -> list:
    return sorted(pool, key=lambda c: c.listen_count, reverse=True)


def mean_random_score(
    pool: list, metric, trials: int = RANDOM_BASELINE_TRIALS
) -> float:
    rng = random.Random(RANDOM_BASELINE_SEED)
    return (
        sum(metric(rng.sample(pool, len(pool))) for _ in range(trials)) / trials
    )


def stage_five_selection(novelty: float) -> list:
    scored = ranked_catalogue(novelty)
    capped = apply_artist_cap(scored, MAX_TRACKS_PER_ARTIST)
    floored = apply_tag_floor(capped, FINAL_K)
    return mmr_select(floored, FINAL_K)


class TestNdcgMetric:
    def test_perfect_ranking_scores_one(self):
        ranked = popularity_ranking(CATALOGUE)
        relevant = {c.mbid for c in ranked[:FINAL_K]}
        assert ndcg_at_k(ranked, relevant, FINAL_K) == 1.0

    def test_relevant_at_the_bottom_scores_below_one(self):
        ranked = ranked_catalogue(0)
        relevant = {ranked[-1].mbid}
        assert (
            0
            < ndcg_at_k(
                ranked[:FINAL_K] + ranked[FINAL_K:], relevant, len(ranked)
            )
            < 1
        )

    def test_empty_relevant_scores_zero(self):
        assert ndcg_at_k(ranked_catalogue(0), set(), FINAL_K) == 0.0

    def test_rewards_relevant_items_placed_earlier(self):
        relevant = {"g1-1"}
        early = [c for c in CATALOGUE if c.mbid == "g1-1"] + [
            c for c in CATALOGUE if c.mbid != "g1-1"
        ]
        late = early[1:FINAL_K] + [early[0]] + early[FINAL_K:]
        assert ndcg_at_k(early, relevant, FINAL_K) > ndcg_at_k(
            late, relevant, FINAL_K
        )


class TestSelfInformationMetric:
    def test_obscure_list_carries_more_bits_than_popular_list(self):
        by_listens = popularity_ranking(CATALOGUE)
        popular_first = mean_self_information_at_k(
            by_listens, TOTAL_LISTENS, FINAL_K
        )
        obscure_first = mean_self_information_at_k(
            list(reversed(by_listens)), TOTAL_LISTENS, FINAL_K
        )
        assert obscure_first > popular_first

    def test_empty_ranking_scores_zero(self):
        assert mean_self_information_at_k([], TOTAL_LISTENS, FINAL_K) == 0.0

    def test_zero_total_listens_scores_zero(self):
        assert mean_self_information_at_k(CATALOGUE, 0, FINAL_K) == 0.0


class TestBaselineComparison:
    def test_pipeline_beats_random_on_recall(self):
        pipeline = recall_at_k(ranked_catalogue(0.5), RELEVANT, FINAL_K)
        rand = mean_random_score(
            CATALOGUE, lambda r: recall_at_k(r, RELEVANT, FINAL_K)
        )
        assert pipeline > rand

    def test_pipeline_beats_random_on_ndcg(self):
        pipeline = ndcg_at_k(ranked_catalogue(0.5), RELEVANT, FINAL_K)
        rand = mean_random_score(
            CATALOGUE, lambda r: ndcg_at_k(r, RELEVANT, FINAL_K)
        )
        assert pipeline > rand

    def test_popularity_baseline_underperforms_even_random(self):
        popularity = recall_at_k(
            popularity_ranking(CATALOGUE), RELEVANT, FINAL_K
        )
        rand = mean_random_score(
            CATALOGUE, lambda r: recall_at_k(r, RELEVANT, FINAL_K)
        )
        pipeline = recall_at_k(ranked_catalogue(0.5), RELEVANT, FINAL_K)
        assert popularity < rand < pipeline


class TestRelevanceNoveltyFrontier:
    def sweep(self) -> list:
        return [(nov, ranked_catalogue(nov)) for nov in NOVELTY_SWEEP]

    def test_novelty_raises_self_information_monotonically(self):
        bits = [
            mean_self_information_at_k(ranked, TOTAL_LISTENS, FINAL_K)
            for _, ranked in self.sweep()
        ]
        assert all(later >= earlier for earlier, later in zip(bits, bits[1:]))
        assert bits[-1] > bits[0]

    def test_relevance_cost_of_novelty_is_bounded(self):
        precisions = [
            recall_at_k(ranked, RELEVANT, FINAL_K) for _, ranked in self.sweep()
        ]
        rand = mean_random_score(
            CATALOGUE, lambda r: recall_at_k(r, RELEVANT, FINAL_K)
        )
        assert precisions[0] >= precisions[-1]
        assert all(p > rand for p in precisions)

    def test_sweep_explores_more_of_the_catalogue_than_any_single_setting(self):
        tops = [
            {c.mbid for c in ranked[:FINAL_K]} for _, ranked in self.sweep()
        ]
        assert len(set().union(*tops)) > FINAL_K


class TestStageFiveComposition:
    def test_artist_cap_holds_in_the_final_selection(self):
        selected = stage_five_selection(0.5)
        per_artist = {}
        for c in selected:
            per_artist[c.artist] = per_artist.get(c.artist, 0) + 1
        assert max(per_artist.values()) <= MAX_TRACKS_PER_ARTIST

    def test_tag_floor_removes_every_distractor(self):
        selected = stage_five_selection(0.5)
        assert not any(c.mbid.startswith("dis") for c in selected)

    def test_selection_keeps_recall_above_half_despite_the_cap(self):
        selected = stage_five_selection(0.5)
        assert recall_at_k(selected, RELEVANT, FINAL_K) >= 0.5

    def test_composed_selection_is_at_least_as_diverse_as_greedy(self):
        scored = ranked_catalogue(0.5)
        capped = apply_artist_cap(scored, MAX_TRACKS_PER_ARTIST)
        floored = apply_tag_floor(capped, FINAL_K)
        greedy = floored[:FINAL_K]
        assert intralist_diversity(
            mmr_select(floored, FINAL_K)
        ) >= intralist_diversity(greedy)

    def test_selection_spreads_across_artists(self):
        assert unique_artists(stage_five_selection(0.5)) >= FINAL_K // 2
