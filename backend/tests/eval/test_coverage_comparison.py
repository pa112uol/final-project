import pytest

from tests.eval.coverage_benchmark import (
    FINAL_K,
    aggregate_metrics,
    build_scenarios,
    scenario_metrics,
    selections,
)

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("scenario", build_scenarios(), ids=lambda s: s.name)
def test_every_method_returns_the_requested_length(scenario):
    assert all(len(items) == FINAL_K for items in selections(scenario).values())


def test_hard_quota_corrects_the_dominant_seed_imbalance():
    metrics = scenario_metrics(build_scenarios()[0])
    assert metrics["hard quota"]["balance"] > metrics["plain MMR"]["balance"]


def test_hard_quota_exposes_a_precision_cost_when_seed_evidence_is_wrong():
    metrics = scenario_metrics(build_scenarios()[3])
    assert metrics["hard quota"]["precision"] < metrics["xQuAD"]["precision"]


def test_no_method_can_cover_an_unavailable_seed():
    metrics = scenario_metrics(build_scenarios()[-2])
    assert all(
        row["coverage"] == pytest.approx(2 / 3) for row in metrics.values()
    )


def test_hard_quota_has_the_best_mean_balance():
    metrics = aggregate_metrics()
    assert metrics["hard quota"]["balance"] == max(
        row["balance"] for row in metrics.values()
    )


def test_hard_quota_does_not_dominate_every_metric():
    metrics = aggregate_metrics()
    assert metrics["hard quota"]["precision"] < metrics["xQuAD"]["precision"]


def test_mmr_within_the_quota_reduces_round_robin_redundancy():
    metrics = scenario_metrics(build_scenarios()[-1])
    assert metrics["hard quota"]["ild"] > metrics["round robin"]["ild"]
