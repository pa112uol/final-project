from dataclasses import dataclass, replace

from recommendations.diversify import mmr_select, mmr_select_balanced
from recommendations.tags import (
    distinctive_tags_per_seed,
    seeds_matched_by_track,
)
from recommendations.types import LFTag, ScoredCandidate
from tests.eval.test_eval import (
    intralist_diversity,
    seed_balance,
    seed_coverage,
)
from tests.eval.test_eval_offline import ndcg_at_k

FINAL_K = 10
XQUAD_COVERAGE_WEIGHT = 0.5


@dataclass(frozen=True)
class CoverageScenario:
    name: str
    seeds: tuple[tuple[LFTag, ...], ...]
    candidates: tuple[ScoredCandidate, ...]
    relevant: frozenset[str]


def _candidate(mbid: str, tags: list[str], score: float) -> ScoredCandidate:
    return ScoredCandidate(
        title=f"Track {mbid}",
        artist=f"Artist {mbid}",
        artist_mbid=f"artist-{mbid}",
        mbid=mbid,
        duration_ms=None,
        tag_weight_sum=score,
        track_tag_score=score,
        listen_count=1000,
        user_count=100,
        artist_listen_count=0,
        tags=tags,
        final_score=score,
        relevance_score=score,
        novelty_score=0.0,
    )


def _group(
    prefix: str,
    tags: list[str],
    scores: list[float],
) -> list[ScoredCandidate]:
    return [
        _candidate(f"{prefix}{index + 1}", tags, score)
        for index, score in enumerate(scores)
    ]


def _seed(tag: str) -> tuple[LFTag, ...]:
    return (LFTag(name="rock", count=100), LFTag(name=tag, count=60))


def _scenario(
    name: str,
    seeds: tuple[tuple[LFTag, ...], ...],
    relevant_groups: list[list[ScoredCandidate]],
    noise_groups: list[list[ScoredCandidate]] | None = None,
) -> CoverageScenario:
    relevant_candidates = [c for group in relevant_groups for c in group]
    noise_candidates = [c for group in noise_groups or [] for c in group]
    candidates = sorted(
        relevant_candidates + noise_candidates,
        key=lambda candidate: candidate.final_score,
        reverse=True,
    )
    return CoverageScenario(
        name=name,
        seeds=seeds,
        candidates=tuple(candidates),
        relevant=frozenset(c.mbid for c in relevant_candidates),
    )


def build_scenarios() -> list[CoverageScenario]:
    dominant = _scenario(
        "dominant seed",
        (_seed("triphop"), _seed("postpunk")),
        [
            _group(
                "a",
                ["rock", "triphop", "downtempo"],
                [round(0.95 - i * 0.04, 2) for i in range(12)],
            ),
            _group(
                "b",
                ["rock", "postpunk", "gothic"],
                [round(0.70 - i * 0.06, 2) for i in range(8)],
            ),
        ],
    )

    scarce = _scenario(
        "scarce second seed",
        (_seed("funk"), _seed("grunge")),
        [
            _group(
                "c",
                ["rock", "funk"],
                [round(0.96 - i * 0.035, 3) for i in range(10)],
            ),
            _group("d", ["rock", "grunge"], [0.72, 0.68]),
        ],
        [_group("n", ["rock", "grunge"], [0.64, 0.60, 0.56, 0.52])],
    )

    three_seed = _scenario(
        "three uneven seeds",
        (_seed("ambient"), _seed("jazz"), _seed("folk")),
        [
            _group(
                "e",
                ["rock", "ambient"],
                [round(0.95 - i * 0.025, 3) for i in range(12)],
            ),
            _group(
                "f",
                ["rock", "jazz"],
                [round(0.68 - i * 0.04, 2) for i in range(6)],
            ),
            _group(
                "g",
                ["rock", "folk"],
                [round(0.46 - i * 0.05, 2) for i in range(4)],
            ),
        ],
    )

    misleading = _scenario(
        "misleading weak seed",
        (_seed("soul"), _seed("metal")),
        [
            _group(
                "h",
                ["rock", "soul"],
                [round(0.97 - i * 0.035, 3) for i in range(12)],
            )
        ],
        [
            _group(
                "q",
                ["rock", "metal"],
                [round(0.63 - i * 0.04, 2) for i in range(6)],
            )
        ],
    )

    overlap = _scenario(
        "overlapping candidates",
        (_seed("funk"), _seed("grunge")),
        [
            _group(
                "o",
                ["rock", "funk", "grunge"],
                [0.92, 0.88, 0.84, 0.80],
            ),
            _group(
                "i",
                ["rock", "funk"],
                [0.78, 0.74, 0.70, 0.66, 0.62, 0.58],
            ),
            _group(
                "j",
                ["rock", "grunge"],
                [0.76, 0.72, 0.68, 0.64, 0.60, 0.56],
            ),
        ],
    )

    unavailable = _scenario(
        "unavailable third seed",
        (_seed("electronic"), _seed("punk"), _seed("classical")),
        [
            _group(
                "k",
                ["rock", "electronic"],
                [round(0.94 - i * 0.04, 2) for i in range(9)],
            ),
            _group(
                "l",
                ["rock", "punk"],
                [round(0.72 - i * 0.05, 2) for i in range(7)],
            ),
        ],
    )

    within_seed = _scenario(
        "within-seed redundancy",
        (_seed("funk"), _seed("grunge")),
        [
            _group(
                "r",
                ["rock", "funk", "groove"],
                [0.96, 0.94, 0.92, 0.90, 0.88],
            ),
            _group("s", ["rock", "funk", "disco"], [0.78, 0.76, 0.74]),
            _group(
                "t",
                ["rock", "grunge", "seattle"],
                [0.86, 0.84, 0.82, 0.80, 0.78],
            ),
            _group("u", ["rock", "grunge", "sludge"], [0.72, 0.70, 0.68]),
        ],
    )
    return [
        dominant,
        scarce,
        three_seed,
        misleading,
        overlap,
        unavailable,
        within_seed,
    ]


def _seed_matcher(scenario: CoverageScenario):
    distinctive = distinctive_tags_per_seed(
        [list(seed) for seed in scenario.seeds]
    )

    def seed_ids_of(candidate) -> set[int]:
        return seeds_matched_by_track(candidate.tags, distinctive)

    return distinctive, seed_ids_of


def round_robin_select(
    ranked: list, k: int, seed_ids_of, seed_count: int
) -> list:
    """Alternate seed groups, taking their highest-ranked unused candidate."""
    remaining = list(ranked)
    selected = []
    while len(selected) < k and remaining:
        progressed = False
        for seed in range(seed_count):
            chosen = next(
                (c for c in remaining if seed in seed_ids_of(c)), None
            )
            if chosen is None:
                continue
            selected.append(chosen)
            remaining = [c for c in remaining if c is not chosen]
            progressed = True
            if len(selected) == k:
                break
        if not progressed:
            break
    selected.extend(remaining[: k - len(selected)])
    return selected


# Evaluation-only adaptation of xQuAD, Santos et al. (2010).
# https://doi.org/10.1007/978-3-642-12275-0_11
# Seed-specific tag matches represent query aspects. A binary match gives
# P(d|qi), while final_score supplies P(d|q). Equal priors avoid favouring a
# seed before observing evidence. This comparator is not used in production.
def xquad_select(
    ranked: list,
    k: int,
    seed_ids_of,
    seed_count: int,
    coverage_weight: float = XQUAD_COVERAGE_WEIGHT,
) -> list:
    if seed_count <= 0:
        return list(ranked[:k])
    remaining = list(ranked)
    selected = []
    unsatisfied = [1.0] * seed_count
    prior = 1.0 / seed_count

    while len(selected) < k and remaining:
        best_index = 0
        best_score = float("-inf")
        for index, candidate in enumerate(remaining):
            matched = seed_ids_of(candidate)
            aspect_utility = sum(
                prior * unsatisfied[seed]
                for seed in matched
                if seed < seed_count
            )
            score = (
                1 - coverage_weight
            ) * candidate.final_score + coverage_weight * aspect_utility
            if score > best_score:
                best_index = index
                best_score = score
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        for seed in seed_ids_of(chosen):
            if seed < seed_count:
                unsatisfied[seed] = 0.0
    return selected


def selections(scenario: CoverageScenario) -> dict[str, list]:
    distinctive, seed_ids_of = _seed_matcher(scenario)
    ranked = [replace(candidate) for candidate in scenario.candidates]
    return {
        "plain MMR": mmr_select([replace(c) for c in ranked], FINAL_K),
        "round robin": round_robin_select(
            [replace(c) for c in ranked], FINAL_K, seed_ids_of, len(distinctive)
        ),
        "xQuAD": xquad_select(
            [replace(c) for c in ranked], FINAL_K, seed_ids_of, len(distinctive)
        ),
        "hard quota": mmr_select_balanced(
            [replace(c) for c in ranked], FINAL_K, seed_ids_of, len(distinctive)
        ),
    }


def scenario_metrics(scenario: CoverageScenario) -> dict[str, dict[str, float]]:
    distinctive, _ = _seed_matcher(scenario)
    result = {}
    for method, selected in selections(scenario).items():
        result[method] = {
            "precision": sum(c.mbid in scenario.relevant for c in selected)
            / len(selected),
            "ndcg": ndcg_at_k(selected, set(scenario.relevant), FINAL_K),
            "coverage": seed_coverage(selected, distinctive),
            "balance": seed_balance(selected, distinctive),
            "ild": intralist_diversity(selected),
        }
    return result


def aggregate_metrics() -> dict[str, dict[str, float]]:
    scenarios = build_scenarios()
    per_scenario = [scenario_metrics(scenario) for scenario in scenarios]
    methods = per_scenario[0].keys()
    metric_names = per_scenario[0][next(iter(methods))].keys()
    return {
        method: {
            metric: sum(row[method][metric] for row in per_scenario)
            / len(per_scenario)
            for metric in metric_names
        }
        for method in methods
    }
