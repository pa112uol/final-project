from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from recommendations.constants import (
    MAX_TRACKS_PER_ARTIST,
    MMR_LAMBDA,
    RECOMMENDATION_LIMIT,
)
from recommendations.pipeline import (
    apply_artist_cap,
    build_scored_pool,
    select_from_pool,
    tag_floor_applies,
)
from recommendations.types import ScoredCandidate, Seed
from recommendations.utils import get_field
from evaluation.playlist_catalogue import (
    DEFAULT_CATALOGUE_PATH,
    EVIDENCE_DIR,
    Case,
    load_cases,
)
from evaluation.retrieval_metrics import (
    RankScores,
    SeedBalance,
    artist_concentration,
    build_relevance,
    list_diversity,
    matched_ids,
    mean_defined,
    mean_field,
    paired_difference,
    rank_scores,
    recall,
    seed_balance,
    seed_counts,
)

logger = logging.getLogger(__name__)

DEFAULT_POOLS_PATH = EVIDENCE_DIR / "playlist-pools.json"
DEFAULT_RESULTS_PATH = EVIDENCE_DIR / "retrieval-ranking-results.json"
DEFAULT_SUMMARY_PATH = EVIDENCE_DIR / "retrieval-ranking-summary.md"
DEFAULT_COMPARISON_PATH = EVIDENCE_DIR / "pool-comparison.md"

# The slider midpoint, matching the controlled evaluation's headline setting
NOVELTY = 0.5
TOP_K = RECOMMENDATION_LIMIT
# Retrieved candidates keep only what matching needs, the scored pool keeps everything
RETRIEVED_FIELDS = ("title", "artist", "artist_mbid", "mbid")
DEFAULT_MAX_PASSES = 5

# Loggers whose warnings report an upstream call that returned no data
UPSTREAM_LOGGERS = ("recommendations", "clients")
# Warnings that lose nothing: a retry about to happen, or a mood with no matches
BENIGN_WARNING_PATTERN = re.compile(r"retrying|matched none of")


@dataclass(frozen=True)
class Configuration:
    name: str
    label: str
    artist_cap: int | None
    mmr_lambda: float


# MMR off means lambda 1.0 inside the production selector, not a plain top-k,
# so seed-balanced quota filling stays on in every configuration
CONFIGURATIONS = (
    Configuration("baseline", "Baseline", None, 1.0),
    Configuration("cap_only", "Cap only", MAX_TRACKS_PER_ARTIST, 1.0),
    Configuration("mmr_only", "MMR only", None, MMR_LAMBDA),
    Configuration(
        "production", "Production", MAX_TRACKS_PER_ARTIST, MMR_LAMBDA
    ),
)

# What each mechanism adds alone, and what each adds on top of the other
CONTRASTS = (
    ("cap_only", "baseline"),
    ("mmr_only", "baseline"),
    ("production", "cap_only"),
    ("production", "mmr_only"),
)


@dataclass
class FrozenPool:
    case_id: str
    seed_tag_sets: list
    retrieved: list
    scored: list
    error: str | None = None


def seed_from_track(track) -> Seed:
    return Seed(
        mbid=track.recording_mbid, title=track.title, artist=track.artist
    )


def tag_to_dict(tag) -> dict:
    return {"name": get_field(tag, "name"), "count": get_field(tag, "count")}


def pool_to_dict(pool: FrozenPool) -> dict:
    return {
        "case_id": pool.case_id,
        "error": pool.error,
        "seed_tag_sets": [
            [tag_to_dict(tag) for tag in tags] for tags in pool.seed_tag_sets
        ],
        "retrieved": [
            {name: get_field(c, name) for name in RETRIEVED_FIELDS}
            for c in pool.retrieved
        ],
        "scored": [asdict(c) for c in pool.scored],
    }


def pool_from_dict(data: dict) -> FrozenPool:
    known = {f.name for f in fields(ScoredCandidate)}
    return FrozenPool(
        case_id=data["case_id"],
        error=data.get("error"),
        seed_tag_sets=data["seed_tag_sets"],
        retrieved=data["retrieved"],
        scored=[
            ScoredCandidate(**{k: v for k, v in c.items() if k in known})
            for c in data["scored"]
        ],
    )


def load_pools(path: Path) -> dict[str, FrozenPool]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {pool["case_id"]: pool_from_dict(pool) for pool in payload["pools"]}


def save_pools(path: Path, pools: dict[str, FrozenPool]) -> None:
    payload = {
        "novelty": NOVELTY,
        "pools": [pool_to_dict(pool) for pool in pools.values()],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class UpstreamFailureLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.failures: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if not BENIGN_WARNING_PATTERN.search(message):
            self.failures.append(message)


# Collects every upstream failure logged inside the block
@contextmanager
def upstream_failures():
    handler = UpstreamFailureLog()
    loggers = [logging.getLogger(name) for name in UPSTREAM_LOGGERS]
    for upstream_logger in loggers:
        upstream_logger.addHandler(handler)
    try:
        yield handler.failures
    finally:
        for upstream_logger in loggers:
            upstream_logger.removeHandler(handler)


def failed_pool(case_id: str, error: str) -> FrozenPool:
    return FrozenPool(case_id, [], [], [], error=error)


# A case whose seeds have no tags keeps an empty pool, which analysis counts
# as an empty result rather than dropping the case
async def freeze_pool(case: Case, api_key: str, clients) -> FrozenPool:
    seeds = [seed_from_track(track) for track in case.seeds]
    pool = await build_scored_pool(seeds, api_key, None, NOVELTY, clients)
    if pool is None:
        return FrozenPool(case.case_id, [[] for _ in seeds], [], [])
    return FrozenPool(
        case.case_id, pool.seed_tag_sets, pool.retrieved, pool.scored
    )


# Freezes one case, or returns a failed pool if it raised or any upstream call
# failed along the way, since the pipeline degrades instead of raising
async def freeze_case(case: Case, api_key: str, clients) -> FrozenPool:
    with upstream_failures() as failures:
        try:
            pool = await freeze_pool(case, api_key, clients)
        except Exception as exc:
            return failed_pool(case.case_id, f"{type(exc).__name__}: {exc}")
    if failures:
        return failed_pool(
            case.case_id,
            f"{len(failures)} upstream failures, first: {failures[0]}",
        )
    return pool


def pending_cases(
    cases: list[Case], pools: dict[str, FrozenPool]
) -> list[Case]:
    return [
        case
        for case in cases
        if case.case_id not in pools or pools[case.case_id].error is not None
    ]


# Freezes every case that has no clean pool yet, passing over the failures
# again until none remain or the passes run out. Saves after every case
async def collect(
    cases: list[Case],
    pools_path: Path,
    api_key: str,
    clients,
    max_passes: int = DEFAULT_MAX_PASSES,
) -> dict[str, FrozenPool]:
    pools = load_pools(pools_path)
    for pass_number in range(1, max_passes + 1):
        pending = pending_cases(cases, pools)
        if not pending:
            break
        logger.info("pass %d: %d cases to freeze", pass_number, len(pending))
        for position, case in enumerate(pending, 1):
            pools[case.case_id] = await freeze_case(case, api_key, clients)
            status = pools[case.case_id].error or "frozen"
            logger.info(
                "[%d/%d] %s %s", position, len(pending), case.case_id, status
            )
            save_pools(pools_path, pools)
    return pools


@dataclass(frozen=True)
class ConfigurationOutcome:
    track: RankScores
    artist: RankScores
    ild: float
    unique_artists: int
    max_artist_share: float
    mean_relevance_score: float
    seed: SeedBalance | None
    tag_floor_fallback: bool
    short_list: bool
    empty_list: bool
    selected: list[str]


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    group: str
    seed_count: int
    held_out_tracks: int
    held_out_artists: int
    retrieved_size: int
    rankable_size: int
    track_recall_retrieved: float
    track_recall_rankable: float
    artist_recall_retrieved: float
    artist_recall_rankable: float
    configurations: dict[str, ConfigurationOutcome]


def describe(candidate) -> str:
    return f"{get_field(candidate, 'artist')} - {get_field(candidate, 'title')}"


# Replays one configuration on a private copy, since selection stamps a
# selection_reason onto the candidates it picks
def evaluate_configuration(
    pool: FrozenPool, relevance, configuration: Configuration
) -> ConfigurationOutcome:
    scored = copy.deepcopy(pool.scored)
    capped = (
        scored
        if configuration.artist_cap is None
        else apply_artist_cap(scored, configuration.artist_cap)
    )
    selected = select_from_pool(
        scored,
        pool.seed_tag_sets,
        TOP_K,
        configuration.artist_cap,
        configuration.mmr_lambda,
    )
    concentration = artist_concentration(selected)
    return ConfigurationOutcome(
        track=rank_scores(
            selected,
            matched_ids(scored, relevance.track_id),
            relevance.track_id,
            TOP_K,
        ),
        artist=rank_scores(
            selected,
            matched_ids(scored, relevance.artist_id),
            relevance.artist_id,
            TOP_K,
        ),
        ild=list_diversity(selected),
        unique_artists=concentration.unique_artists,
        max_artist_share=concentration.max_artist_share,
        mean_relevance_score=mean_field(selected, "relevance_score"),
        seed=seed_balance(seed_counts(selected, pool.seed_tag_sets), TOP_K),
        tag_floor_fallback=bool(capped)
        and not tag_floor_applies(capped, TOP_K),
        short_list=len(selected) < TOP_K,
        empty_list=not selected,
        selected=[describe(c) for c in selected],
    )


def evaluate_case(case: Case, pool: FrozenPool) -> CaseOutcome:
    relevance = build_relevance(case.held_out)
    return CaseOutcome(
        case_id=case.case_id,
        group=case.group,
        seed_count=len(case.seeds),
        held_out_tracks=relevance.track_count,
        held_out_artists=relevance.artist_count,
        retrieved_size=len(pool.retrieved),
        rankable_size=len(pool.scored),
        track_recall_retrieved=recall(
            matched_ids(pool.retrieved, relevance.track_id),
            relevance.track_count,
        ),
        track_recall_rankable=recall(
            matched_ids(pool.scored, relevance.track_id), relevance.track_count
        ),
        artist_recall_retrieved=recall(
            matched_ids(pool.retrieved, relevance.artist_id),
            relevance.artist_count,
        ),
        artist_recall_rankable=recall(
            matched_ids(pool.scored, relevance.artist_id),
            relevance.artist_count,
        ),
        configurations={
            configuration.name: evaluate_configuration(
                pool, relevance, configuration
            )
            for configuration in CONFIGURATIONS
        },
    )


def _seed_value(outcome: ConfigurationOutcome, name: str) -> float | None:
    return None if outcome.seed is None else float(getattr(outcome.seed, name))


# Each reported metric as a function of one configuration's outcome.
# None marks a case where the metric is undefined and is left out of its mean
METRICS = {
    "track_precision": lambda o: o.track.precision,
    "track_recall": lambda o: o.track.recall,
    "track_ndcg": lambda o: o.track.ndcg,
    "artist_precision": lambda o: o.artist.precision,
    "artist_recall": lambda o: o.artist.recall,
    "artist_ndcg": lambda o: o.artist.ndcg,
    "mean_relevance_score": lambda o: o.mean_relevance_score,
    "ild": lambda o: o.ild,
    "unique_artists": lambda o: float(o.unique_artists),
    "max_artist_share": lambda o: o.max_artist_share,
    "seed_coverage": lambda o: _seed_value(o, "coverage"),
    "seed_balance": lambda o: _seed_value(o, "balance"),
    "quota_shortfall_rate": lambda o: _seed_value(o, "quota_shortfall"),
    "tag_floor_fallback_rate": lambda o: float(o.tag_floor_fallback),
    "short_list_rate": lambda o: float(o.short_list),
    "empty_list_rate": lambda o: float(o.empty_list),
}

RETRIEVAL_METRICS = (
    "retrieved_size",
    "rankable_size",
    "track_recall_retrieved",
    "track_recall_rankable",
    "artist_recall_retrieved",
    "artist_recall_rankable",
)


def metric_values(
    outcomes: list[CaseOutcome], configuration: str, metric: str
) -> list[float | None]:
    extract = METRICS[metric]
    return [extract(o.configurations[configuration]) for o in outcomes]


def summarise_retrieval(outcomes: list[CaseOutcome]) -> dict:
    summary = {
        name: mean_defined([float(getattr(o, name)) for o in outcomes])
        for name in RETRIEVAL_METRICS
    }
    summary["cases"] = len(outcomes)
    summary["held_out_tracks"] = sum(o.held_out_tracks for o in outcomes)
    summary["cases_with_rankable_track"] = sum(
        o.track_recall_rankable > 0 for o in outcomes
    )
    summary["cases_with_rankable_artist"] = sum(
        o.artist_recall_rankable > 0 for o in outcomes
    )
    return summary


def summarise_configurations(outcomes: list[CaseOutcome]) -> dict:
    return {
        configuration.name: {
            metric: mean_defined(
                metric_values(outcomes, configuration.name, metric)
            )
            for metric in METRICS
        }
        for configuration in CONFIGURATIONS
    }


def summarise_contrasts(outcomes: list[CaseOutcome]) -> dict:
    contrasts = {}
    for treatment, baseline in CONTRASTS:
        contrasts[f"{treatment}_vs_{baseline}"] = {
            metric: (
                asdict(difference)
                if (
                    difference := paired_difference(
                        metric_values(outcomes, treatment, metric),
                        metric_values(outcomes, baseline, metric),
                    )
                )
                else None
            )
            for metric in METRICS
        }
    return contrasts


# Reports one-seed, two-seed and pooled cases separately, since seed coverage
# and balance exist only for the two-seed group. Sampled groups such as genres follow
def summarise(outcomes: list[CaseOutcome]) -> dict:
    groups = {
        "all": outcomes,
        "one_seed": [o for o in outcomes if o.seed_count == 1],
        "two_seed": [o for o in outcomes if o.seed_count >= 2],
    }
    for name in sorted({o.group for o in outcomes if o.group}):
        groups[f"group:{name}"] = [o for o in outcomes if o.group == name]
    return {
        name: {
            "retrieval": summarise_retrieval(group),
            "configurations": summarise_configurations(group),
            "contrasts": summarise_contrasts(group),
        }
        for name, group in groups.items()
        if group
    }


def analyse(
    cases: list[Case], pools: dict[str, FrozenPool]
) -> tuple[list[CaseOutcome], list[str]]:
    outcomes = []
    skipped = []
    for case in cases:
        pool = pools.get(case.case_id)
        if pool is None or pool.error is not None:
            skipped.append(case.case_id)
            continue
        outcomes.append(evaluate_case(case, pool))
    return outcomes, skipped


def format_number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def format_difference(difference: dict | None) -> str:
    if difference is None:
        return "n/a"
    marker = "*" if difference["low"] > 0 or difference["high"] < 0 else ""
    return (
        f"{difference['mean']:+.3f} [{difference['low']:+.3f}, "
        f"{difference['high']:+.3f}]{marker}"
    )


def markdown_table(header: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def format_group(name: str, group: dict) -> str:
    retrieval = group["retrieval"]
    configurations = group["configurations"]
    contrasts = group["contrasts"]
    retrieval_table = markdown_table(
        ["Metric", "Value"],
        [
            [key, format_number(float(value))]
            for key, value in retrieval.items()
        ],
    )
    configuration_table = markdown_table(
        ["Metric", *(c.label for c in CONFIGURATIONS)],
        [
            [
                metric,
                *(
                    format_number(configurations[c.name][metric])
                    for c in CONFIGURATIONS
                ),
            ]
            for metric in METRICS
        ],
    )
    contrast_table = markdown_table(
        ["Metric", *contrasts],
        [
            [
                metric,
                *(
                    format_difference(contrasts[key][metric])
                    for key in contrasts
                ),
            ]
            for metric in METRICS
        ],
    )
    return "\n\n".join(
        [
            f"## {name}",
            "### Retrieval",
            retrieval_table,
            "### Configurations",
            configuration_table,
            "### Paired differences, mean [95% bootstrap CI], * excludes zero",
            contrast_table,
        ]
    )


def format_summary(summary: dict, skipped: list[str]) -> str:
    sections = [format_group(name, group) for name, group in summary.items()]
    if skipped:
        sections.append(f"Skipped cases without a pool: {', '.join(skipped)}")
    return "\n\n".join(["# Retrieval and ranking evaluation", *sections]) + "\n"


# The configuration and metrics a pool comparison reports. Retrieval metrics
# read the case outcome itself, the rest read the configuration's outcome
COMPARED_CONFIGURATION = "production"
COMPARED_RETRIEVAL_METRICS = ("track_recall_rankable", "artist_recall_rankable")
COMPARED_SELECTION_METRICS = (
    "track_precision",
    "track_ndcg",
    "artist_precision",
    "artist_ndcg",
    "ild",
    "unique_artists",
    "seed_coverage",
    "seed_balance",
    "empty_list_rate",
)


# The same cases with every seed reduced to artist and title, as a name-only
# search would send them
def strip_seed_mbids(cases: list[Case]) -> list[Case]:
    return [
        replace(
            case,
            seeds=tuple(
                replace(seed, recording_mbid="") for seed in case.seeds
            ),
        )
        for case in cases
    ]


def has_seed_mbid(case: Case) -> bool:
    return any(seed.recording_mbid for seed in case.seeds)


def comparison_value(outcome: CaseOutcome, metric: str) -> float | None:
    if metric in COMPARED_RETRIEVAL_METRICS:
        return float(getattr(outcome, metric))
    return METRICS[metric](outcome.configurations[COMPARED_CONFIGURATION])


# Means on each side and the paired difference, treatment minus baseline.
# Both lists hold the same cases in the same order
def compare_outcomes(
    treatment: list[CaseOutcome], baseline: list[CaseOutcome]
) -> dict:
    compared = {}
    for metric in (*COMPARED_RETRIEVAL_METRICS, *COMPARED_SELECTION_METRICS):
        after = [comparison_value(o, metric) for o in treatment]
        before = [comparison_value(o, metric) for o in baseline]
        difference = paired_difference(after, before)
        compared[metric] = {
            "treatment_mean": mean_defined(after),
            "baseline_mean": mean_defined(before),
            "difference": asdict(difference) if difference else None,
        }
    return compared


# Pairs the cases both runs froze cleanly. The resolved group keeps only cases
# whose seeds carry an MBID, since the rest were sent identically in both runs
def compare_runs(
    cases: list[Case],
    treatment_pools: dict[str, FrozenPool],
    baseline_pools: dict[str, FrozenPool],
) -> dict:
    complete = [
        case
        for case in cases
        if not pending_cases([case], treatment_pools)
        and not pending_cases([case], baseline_pools)
    ]
    groups = {
        "all": complete,
        "seed_resolved": [case for case in complete if has_seed_mbid(case)],
    }
    return {
        name: {
            "cases": len(group),
            "metrics": compare_outcomes(
                [evaluate_case(c, treatment_pools[c.case_id]) for c in group],
                [evaluate_case(c, baseline_pools[c.case_id]) for c in group],
            ),
        }
        for name, group in groups.items()
        if group
    }


def format_comparison(comparison: dict, treatment: str, baseline: str) -> str:
    sections = [f"# Pool comparison: {treatment} vs {baseline}"]
    for name, group in comparison.items():
        rows = [
            [
                metric,
                format_number(values["treatment_mean"]),
                format_number(values["baseline_mean"]),
                format_difference(values["difference"]),
            ]
            for metric, values in group["metrics"].items()
        ]
        sections.append(f"## {name} ({group['cases']} cases)")
        sections.append(
            markdown_table(
                ["Metric", treatment, baseline, "Difference [95% CI]"], rows
            )
        )
    return "\n\n".join(sections) + "\n"


def run_compare(args: argparse.Namespace) -> None:
    logging.getLogger("recommendations").setLevel(logging.WARNING)
    if args.baseline_pools is None:
        raise SystemExit("compare needs --baseline-pools")
    cases = load_cases(args.catalogue)
    treatment_pools = load_pools(args.pools)
    baseline_pools = load_pools(args.baseline_pools)
    for label, pools in (
        ("pools", treatment_pools),
        ("baseline pools", baseline_pools),
    ):
        if pending_cases(cases, pools) and not args.allow_incomplete:
            raise SystemExit(f"{label} are incomplete, collect them first")
    comparison = compare_runs(cases, treatment_pools, baseline_pools)
    report = format_comparison(
        comparison, args.pools.stem, args.baseline_pools.stem
    )
    args.comparison.write_text(report, encoding="utf-8")
    print(report)


def run_collect(args: argparse.Namespace) -> None:
    from recommendations.index import build_clients
    from tests.live_env import API_KEY

    if not API_KEY:
        raise SystemExit("LASTFM_API_KEY is required for collect")
    cases = load_cases(args.catalogue)
    if args.strip_seed_mbids:
        cases = strip_seed_mbids(cases)
    pools = asyncio.run(
        collect(cases, args.pools, API_KEY, build_clients(), args.max_passes)
    )
    incomplete = [case.case_id for case in pending_cases(cases, pools)]
    if incomplete:
        raise SystemExit(
            f"{len(incomplete)} of {len(cases)} cases still incomplete, "
            f"rerun collect to retry: {', '.join(incomplete)}"
        )
    logger.info("all %d cases frozen", len(cases))


def run_analyse(args: argparse.Namespace) -> None:
    logging.getLogger("recommendations").setLevel(logging.WARNING)
    cases = load_cases(args.catalogue)
    pools = load_pools(args.pools)
    incomplete = pending_cases(cases, pools)
    if incomplete and not args.allow_incomplete:
        raise SystemExit(
            f"{len(incomplete)} of {len(cases)} cases have no clean pool, "
            "run collect until it completes or pass --allow-incomplete"
        )
    outcomes, skipped = analyse(cases, pools)
    summary = summarise(outcomes)
    args.results.write_text(
        json.dumps(
            {
                "novelty": NOVELTY,
                "top_k": TOP_K,
                "configurations": [asdict(c) for c in CONFIGURATIONS],
                "skipped": skipped,
                "summary": summary,
                "cases": [asdict(o) for o in outcomes],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = format_summary(summary, skipped)
    args.summary.write_text(report, encoding="utf-8")
    print(report)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # httpx logs full request URLs at INFO, and Last.fm URLs carry the API key
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect", "analyse", "compare"))
    parser.add_argument(
        "--catalogue", type=Path, default=DEFAULT_CATALOGUE_PATH
    )
    parser.add_argument("--pools", type=Path, default=DEFAULT_POOLS_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--max-passes", type=int, default=DEFAULT_MAX_PASSES)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--strip-seed-mbids", action="store_true")
    parser.add_argument("--baseline-pools", type=Path)
    parser.add_argument(
        "--comparison", type=Path, default=DEFAULT_COMPARISON_PATH
    )
    args = parser.parse_args()
    if args.command == "collect":
        run_collect(args)
    elif args.command == "compare":
        run_compare(args)
    else:
        run_analyse(args)


if __name__ == "__main__":
    main()
