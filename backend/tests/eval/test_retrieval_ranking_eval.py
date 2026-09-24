import logging

import pytest

from recommendations.types import LFTag, ScoredCandidate
from evaluation import retrieval_ranking_eval as ranking_eval
from evaluation.playlist_catalogue import Case, PlaylistTrack
from evaluation.retrieval_metrics import build_relevance
from evaluation.retrieval_ranking_eval import (
    CONFIGURATIONS,
    Configuration,
    FrozenPool,
    analyse,
    collect,
    evaluate_case,
    evaluate_configuration,
    format_summary,
    load_pools,
    pool_from_dict,
    pool_to_dict,
    summarise,
)
from tests.test_pipeline import make_clients

SEED_TAGS = [[LFTag("shoegaze", 100)]]
TWO_SEED_TAGS = [[LFTag("shoegaze", 100)], [LFTag("jazz", 100)]]


def scored(mbid, artist, final_score, tags=("shoegaze",), title=None):
    return ScoredCandidate(
        title=title or f"Song {mbid}",
        artist=artist,
        artist_mbid=f"artist-{artist}",
        mbid=mbid,
        duration_ms=None,
        tag_weight_sum=100,
        track_tag_score=1.0,
        listen_count=0,
        user_count=0,
        artist_listen_count=0,
        tags=list(tags),
        final_score=final_score,
        relevance_score=final_score,
    )


def held_out_track(mbid, artist, title=None):
    return PlaylistTrack(mbid, title or f"Song {mbid}", artist, (f"artist-{artist}",))


def make_case(case_id="c1-1seed", seeds=1, held_out=None):
    seed_tracks = tuple(held_out_track(f"seed-{i}", f"Seed {i}") for i in range(seeds))
    return Case(
        case_id=case_id,
        playlist_mbid="pl",
        creator_hash="hash",
        seeds=seed_tracks,
        held_out=tuple(held_out or [held_out_track("r1", "Rel")]),
    )


# One artist owns the top of the score order, so the cap and MMR both have work to do
@pytest.fixture
def crowded_pool():
    candidates = [scored(f"a{i}", "Dominant", 1.0 - i * 0.01) for i in range(8)]
    candidates += [
        scored(f"o{i}", f"Other {i}", 0.5 - i * 0.01, tags=(f"tag{i}",))
        for i in range(8)
    ]
    candidates.append(scored("r1", "Rel", 0.45))
    return FrozenPool("c1-1seed", SEED_TAGS, candidates[:10], candidates)


class TestPoolSerialisation:
    def test_round_trip_preserves_scored_candidates(self, crowded_pool):
        restored = pool_from_dict(pool_to_dict(crowded_pool))
        assert restored.scored == crowded_pool.scored
        assert restored.seed_tag_sets == [[{"name": "shoegaze", "count": 100}]]

    def test_retrieved_keeps_only_matching_fields(self, crowded_pool):
        retrieved = pool_to_dict(crowded_pool)["retrieved"][0]
        assert set(retrieved) == set(ranking_eval.RETRIEVED_FIELDS)


class TestEvaluateConfiguration:
    def test_does_not_mutate_the_frozen_pool(self, crowded_pool):
        before = [c.selection_reason for c in crowded_pool.scored]
        relevance = build_relevance(make_case().held_out)
        for configuration in CONFIGURATIONS:
            evaluate_configuration(crowded_pool, relevance, configuration)
        assert [c.selection_reason for c in crowded_pool.scored] == before

    def test_baseline_is_concentrated_and_production_is_not(self, crowded_pool):
        relevance = build_relevance(make_case().held_out)
        baseline, production = (
            evaluate_configuration(crowded_pool, relevance, configuration)
            for configuration in (CONFIGURATIONS[0], CONFIGURATIONS[-1])
        )
        assert baseline.max_artist_share == 0.8
        assert production.max_artist_share <= 0.2
        assert production.unique_artists > baseline.unique_artists

    def test_flags_a_short_list(self):
        pool = FrozenPool("c", SEED_TAGS, [], [scored("x", "X", 0.5)])
        relevance = build_relevance(make_case().held_out)
        outcome = evaluate_configuration(pool, relevance, CONFIGURATIONS[0])
        assert outcome.short_list and not outcome.empty_list
        assert outcome.tag_floor_fallback

    def test_flags_an_empty_list_without_a_floor_fallback(self):
        pool = FrozenPool("c", SEED_TAGS, [], [])
        relevance = build_relevance(make_case().held_out)
        outcome = evaluate_configuration(pool, relevance, CONFIGURATIONS[0])
        assert outcome.empty_list
        assert not outcome.tag_floor_fallback

    def test_reports_seed_balance_only_for_two_seeds(self, crowded_pool):
        relevance = build_relevance(make_case().held_out)
        one = evaluate_configuration(crowded_pool, relevance, CONFIGURATIONS[-1])
        crowded_pool.seed_tag_sets = TWO_SEED_TAGS
        two = evaluate_configuration(crowded_pool, relevance, CONFIGURATIONS[-1])
        assert one.seed is None
        assert two.seed is not None


class TestEvaluateCase:
    def test_measures_recall_at_both_stages(self, crowded_pool):
        case = make_case(
            held_out=[held_out_track("r1", "Rel"), held_out_track("r2", "Missing")]
        )
        outcome = evaluate_case(case, crowded_pool)
        assert outcome.track_recall_retrieved == 0.0
        assert outcome.track_recall_rankable == 0.5
        assert outcome.artist_recall_rankable == 0.5
        assert set(outcome.configurations) == {c.name for c in CONFIGURATIONS}

    def test_ranking_metrics_undefined_when_nothing_rankable(self, crowded_pool):
        case = make_case(held_out=[held_out_track("zz", "Nobody")])
        outcome = evaluate_case(case, crowded_pool)
        production = outcome.configurations["production"]
        assert production.track.ndcg is None
        assert production.track.precision == 0.0


class TestAnalyseAndSummarise:
    def test_skips_missing_and_failed_pools(self, crowded_pool):
        cases = [make_case("c1-1seed"), make_case("c2-1seed"), make_case("c3-1seed")]
        pools = {
            "c1-1seed": crowded_pool,
            "c3-1seed": FrozenPool("c3-1seed", [], [], [], error="boom"),
        }
        outcomes, skipped = analyse(cases, pools)
        assert [o.case_id for o in outcomes] == ["c1-1seed"]
        assert skipped == ["c2-1seed", "c3-1seed"]

    def test_groups_by_seed_count(self, crowded_pool):
        two_seed_pool = FrozenPool(
            "c1-2seed", TWO_SEED_TAGS, [], list(crowded_pool.scored)
        )
        cases = [make_case("c1-1seed"), make_case("c1-2seed", seeds=2)]
        outcomes, _ = analyse(
            cases, {"c1-1seed": crowded_pool, "c1-2seed": two_seed_pool}
        )
        summary = summarise(outcomes)
        assert set(summary) == {"all", "one_seed", "two_seed"}
        one_seed = summary["one_seed"]["configurations"]["production"]
        two_seed = summary["two_seed"]["configurations"]["production"]
        assert one_seed["seed_coverage"] is None
        assert two_seed["seed_coverage"] is not None

    def test_adds_a_section_per_sampled_group(self, crowded_pool):
        case = Case("c1-1seed", "pl", "hash", (held_out_track("s", "S"),),
                    (held_out_track("r1", "Rel"),), group="indie")
        outcomes, _ = analyse([case], {"c1-1seed": crowded_pool})
        assert "group:indie" in summarise(outcomes)

    def test_summary_mentions_every_configuration(self, crowded_pool):
        outcomes, skipped = analyse([make_case()], {"c1-1seed": crowded_pool})
        text = format_summary(summarise(outcomes), skipped)
        for configuration in CONFIGURATIONS:
            assert configuration.label in text


class TestConfigurations:
    def test_cover_the_two_by_two_design(self):
        cells = {(c.artist_cap is not None, c.mmr_lambda < 1.0) for c in CONFIGURATIONS}
        assert cells == {(False, False), (True, False), (False, True), (True, True)}

    def test_are_immutable(self):
        with pytest.raises(AttributeError):
            Configuration("x", "X", None, 1.0).name = "y"


class TestCollect:
    async def test_freezes_pools_and_resumes(self, tmp_path):
        pools_path = tmp_path / "pools.json"
        case = Case(
            "live-1seed",
            "pl",
            "hash",
            (PlaylistTrack("seed-mbid-1", "souvlaki space station", "slowdive", ()),),
            (held_out_track("rec-alison", "Ride"),),
        )
        pools = await collect([case], pools_path, "key", make_clients())
        assert pools["live-1seed"].scored
        assert load_pools(pools_path)["live-1seed"].error is None

        async def unreachable(*args, **kwargs):
            raise AssertionError("a frozen case must not be fetched again")

        await collect([case], pools_path, "key", make_clients(fetch_track_tags=unreachable))

    async def test_records_a_failure_and_retries_it_next_run(self, tmp_path):
        pools_path = tmp_path / "pools.json"
        case = make_case("bad-1seed")

        async def broken(*args, **kwargs):
            raise RuntimeError("upstream down")

        pools = await collect(
            [case], pools_path, "key", make_clients(fetch_track_tags=broken)
        )
        assert "upstream down" in pools["bad-1seed"].error
        pools = await collect([case], pools_path, "key", make_clients())
        assert pools["bad-1seed"].error is None


class TestSeedMbidComparison:
    def _case(self, case_id, mbid):
        seed = PlaylistTrack(mbid, "Seed", "Seed Artist", (), "spotify:track:s")
        return Case(case_id, "pl", "hash", (seed,), (held_out_track("r1", "Rel"),))

    def test_strip_removes_only_seed_mbids(self):
        stripped = ranking_eval.strip_seed_mbids([self._case("c-1seed", "m1")])[0]
        assert stripped.seeds[0].recording_mbid == ""
        assert stripped.seeds[0].track_id == "spotify:track:s"
        assert stripped.held_out[0].recording_mbid == "r1"

    def test_identical_pools_differ_by_nothing(self, crowded_pool):
        case = self._case("c1-1seed", "m1")
        pools = {"c1-1seed": crowded_pool}
        comparison = ranking_eval.compare_runs([case], pools, pools)
        recall = comparison["all"]["metrics"]["artist_recall_rankable"]
        assert recall["difference"]["mean"] == 0.0

    def test_resolved_group_keeps_only_cases_with_seed_mbids(self, crowded_pool):
        cases = [self._case("c1-1seed", "m1"), self._case("c2-1seed", "")]
        pools = {"c1-1seed": crowded_pool, "c2-1seed": crowded_pool}
        comparison = ranking_eval.compare_runs(cases, pools, pools)
        assert comparison["all"]["cases"] == 2
        assert comparison["seed_resolved"]["cases"] == 1

    def test_detects_a_retrieval_gain(self, crowded_pool):
        case = self._case("c1-1seed", "m1")
        without = FrozenPool("c1-1seed", SEED_TAGS, [], crowded_pool.scored[:-1])
        comparison = ranking_eval.compare_runs(
            [case], {"c1-1seed": crowded_pool}, {"c1-1seed": without}
        )
        recall = comparison["all"]["metrics"]["track_recall_rankable"]
        assert recall["treatment_mean"] == 1.0
        assert recall["baseline_mean"] == 0.0

    def test_skips_cases_missing_from_either_run(self, crowded_pool):
        cases = [self._case("c1-1seed", "m1"), self._case("c2-1seed", "m2")]
        comparison = ranking_eval.compare_runs(
            cases, {"c1-1seed": crowded_pool}, {"c1-1seed": crowded_pool,
                                                "c2-1seed": crowded_pool}
        )
        assert comparison["all"]["cases"] == 1

    def test_report_names_both_runs(self, crowded_pool):
        case = self._case("c1-1seed", "m1")
        pools = {"c1-1seed": crowded_pool}
        text = ranking_eval.format_comparison(
            ranking_eval.compare_runs([case], pools, pools), "with-mbid", "name-only"
        )
        assert "with-mbid" in text and "name-only" in text


class TestUpstreamFailureCapture:
    def test_records_upstream_warnings(self):
        with ranking_eval.upstream_failures() as failures:
            logging.getLogger("clients.lastfm").warning("Last.fm HTTP 500")
        assert failures == ["Last.fm HTTP 500"]

    def test_ignores_retries_and_unrelated_loggers(self):
        with ranking_eval.upstream_failures() as failures:
            logging.getLogger("clients.musicbrainz").warning("MB fetch failed, retrying")
            logging.getLogger("caching.circuit").warning("Redis recovered")
            logging.getLogger("clients.lastfm").info("fine")
        assert failures == []

    def test_detaches_after_the_block(self):
        with ranking_eval.upstream_failures() as failures:
            pass
        logging.getLogger("clients.lastfm").warning("after")
        assert failures == []


class TestCollectCompleteness:
    async def test_a_degraded_run_is_not_frozen(self, tmp_path):
        async def tag_artists_down(tag, page, limit, api_key):
            raise RuntimeError("Last.fm down")

        pools = await collect(
            [make_case("deg-1seed")],
            tmp_path / "pools.json",
            "key",
            make_clients(fetch_tag_artists=tag_artists_down),
            max_passes=1,
        )
        assert "upstream failures" in pools["deg-1seed"].error

    async def test_a_transient_failure_recovers_within_one_call(self, tmp_path):
        calls = []
        healthy = make_clients().fetch_track_tags

        async def flaky(title, artist, api_key, mbid=None):
            calls.append(title)
            if len(calls) == 1:
                raise RuntimeError("blip")
            return await healthy(title, artist, api_key, mbid)

        pools = await collect(
            [make_case("flaky-1seed")],
            tmp_path / "pools.json",
            "key",
            make_clients(fetch_track_tags=flaky),
        )
        assert pools["flaky-1seed"].error is None
        assert len(calls) == 2

    def test_pending_cases_lists_missing_and_failed(self, crowded_pool):
        cases = [make_case("ok-1seed"), make_case("bad-1seed"), make_case("new-1seed")]
        pools = {
            "ok-1seed": crowded_pool,
            "bad-1seed": FrozenPool("bad-1seed", [], [], [], error="x"),
        }
        pending = ranking_eval.pending_cases(cases, pools)
        assert [case.case_id for case in pending] == ["bad-1seed", "new-1seed"]
