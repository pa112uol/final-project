"""
User-simulation quality tests for the recommendation pipeline.

Each scenario mirrors a realistic user search: mainstream pop, hip-hop,
classic rock, ultra-niche, multi-seed crossover, and intermediate novelty.
Quality metrics are printed and asserted per scenario.

Run with: pytest tests/test_pipeline_usersim.py -s -v

Mirrors the assertions defined in pipeline.usersim.test.ts.
"""

import os
import time
import asyncio
from pathlib import Path
import pytest
from recommendations.index import get_recommendations
from recommendations.types import Track


def _load_env():
    """Load env vars from the standard locations, closest file wins."""
    backend_dir = Path(__file__).resolve().parent.parent
    candidates = [
        # backend/.env
        backend_dir / ".env",
        # backend/.env.local
        backend_dir / ".env.local",
        # project root .env.local (Next.js convention)
        backend_dir.parent / ".env.local",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            m_line = line.strip()
            if not m_line or m_line.startswith("#"):
                continue
            if "=" in m_line:
                key, _, value = m_line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value:
                    os.environ.setdefault(key, value)


_load_env()

API_KEY = os.environ.get("LASTFM_API_KEY", "")

BROAD_LABELS = {
    "rock",
    "pop",
    "metal",
    "electronic",
    "indie",
    "alternative",
    "folk",
    "jazz",
    "classical",
    "hip hop",
    "rap",
    "country",
    "soul",
    "blues",
    "r&b",
    "dance",
    "punk",
}


def analyse_quality(label: str, tracks: list) -> dict:
    if not tracks:
        return {
            "scenario": label,
            "track_count": 0,
            "unique_artists": 0,
            "artist_diversity": 0,
            "avg_relevance": 0,
            "min_relevance": 0,
            "relevance_spread": 0,
            "avg_novelty": 0,
            "tracks_with_zero_relevance": 0,
            "tracks_with_sparse_tags": 0,
        }
    artists = {t.artist.lower() for t in tracks}
    relevances = [t.relevance_score for t in tracks]
    avg_rel = sum(relevances) / len(relevances)
    max_rel = max(relevances)
    min_rel = min(relevances)
    return {
        "scenario": label,
        "track_count": len(tracks),
        "unique_artists": len(artists),
        "artist_diversity": len(artists) / len(tracks),
        "avg_relevance": avg_rel,
        "min_relevance": min_rel,
        "relevance_spread": max_rel - min_rel,
        "avg_novelty": sum(t.novelty_score for t in tracks) / len(tracks),
        "tracks_with_zero_relevance": sum(1 for r in relevances if r < 0.01),
        "tracks_with_sparse_tags": 0,
    }


def print_quality(report: dict, tracks: list):
    print(f"\n{'=' * 60}")
    print(f"[QUALITY] {report['scenario']}")
    diversity_pct = report["artist_diversity"] * 100
    print(
        f"tracks: {report['track_count']}  unique artists: "
        f"{report['unique_artists']}/{report['track_count']} "
        f"({diversity_pct:.0f}% diversity)"
    )
    print(
        f"  relevance - avg:{report['avg_relevance']:.3f}  "
        f"min:{report['min_relevance']:.3f}  "
        f"spread:{report['relevance_spread']:.3f}"
    )
    print(f"  novelty  - avg:{report['avg_novelty']:.3f}")
    if report["tracks_with_zero_relevance"] > 0:
        print(
            f"WARNING: {report['tracks_with_zero_relevance']} track(s) with relevance < 0.01"
        )
    print("  results:")
    for i, t in enumerate(tracks):
        print(
            f'[{i + 1}] "{t.title}" - {t.artist}'
            f"  rel:{t.relevance_score:.3f} nov:{t.novelty_score:.3f}"
        )
    print("=" * 60)


def assert_shape(t: Track):
    assert isinstance(t.title, str)
    assert len(t.title) > 0
    assert isinstance(t.artist, str)
    assert t.relevance_score >= 0
    assert t.relevance_score <= 1
    assert t.novelty_score >= 0
    assert t.novelty_score <= 1


def assert_artist_cap(tracks: list):
    counts = {}
    for t in tracks:
        key = t.artist.lower()
        counts[key] = counts.get(key, 0) + 1
    for artist, n in counts.items():
        assert n <= 2, f"{artist} exceeded artist cap of 2"


# Fixtures that run the full pipeline once per class


@pytest.fixture(scope="class")
def synth_pop_tracks():
    if not API_KEY:
        return None
    t_start = time.perf_counter()
    result = asyncio.run(
        get_recommendations(
            [{"mbid": "", "title": "blinding lights", "artist": "the weeknd"}],
            API_KEY,
            None,
            0,
        )
    )
    print(
        f"\n[TIME] UserSim A (synth-pop): {time.perf_counter() - t_start:.2f}s"
    )
    return result


@pytest.fixture(scope="class")
def hip_hop_tracks():
    if not API_KEY:
        return None
    t_start = time.perf_counter()
    result = asyncio.run(
        get_recommendations(
            [{"mbid": "", "title": "humble", "artist": "kendrick lamar"}],
            API_KEY,
            None,
            0,
        )
    )
    print(f"\n[TIME] UserSim B (hip-hop): {time.perf_counter() - t_start:.2f}s")
    return result


@pytest.fixture(scope="class")
def classic_rock_tracks():
    if not API_KEY:
        return None
    t_start = time.perf_counter()
    result = asyncio.run(
        get_recommendations(
            [
                {
                    "mbid": "",
                    "title": "stairway to heaven",
                    "artist": "led zeppelin",
                }
            ],
            API_KEY,
            None,
            0,
        )
    )
    print(
        f"\n[TIME] UserSim C (classic rock): {time.perf_counter() - t_start:.2f}s"
    )
    return result


@pytest.fixture(scope="class")
def ultra_niche_tracks():
    if not API_KEY:
        return None
    t_start = time.perf_counter()
    result = asyncio.run(
        get_recommendations(
            [{"mbid": "", "title": "alien observer", "artist": "grouper"}],
            API_KEY,
            None,
            0,
        )
    )
    print(
        f"\n[TIME] UserSim D (ultra-niche): {time.perf_counter() - t_start:.2f}s"
    )
    return result


@pytest.fixture(scope="class")
def multi_seed_tracks():
    if not API_KEY:
        return None, None, None

    async def _gather():
        return await asyncio.gather(
            get_recommendations(
                [
                    {
                        "mbid": "",
                        "title": "bloodbuzz ohio",
                        "artist": "the national",
                    }
                ],
                API_KEY,
                None,
                0,
            ),
            get_recommendations(
                [{"mbid": "", "title": "skinny love", "artist": "bon iver"}],
                API_KEY,
                None,
                0,
            ),
            get_recommendations(
                [
                    {
                        "mbid": "",
                        "title": "bloodbuzz ohio",
                        "artist": "the national",
                    },
                    {"mbid": "", "title": "skinny love", "artist": "bon iver"},
                ],
                API_KEY,
                None,
                0,
            ),
        )

    t_start = time.perf_counter()
    national, bon_iver, multi = asyncio.run(_gather())
    print(
        f"\n[TIME] UserSim E (multi-seed, 3x parallel): {time.perf_counter() - t_start:.2f}s"
    )
    return national, bon_iver, multi


@pytest.fixture(scope="class")
def novelty_gradient_tracks():
    if not API_KEY:
        return None, None, None
    seed = [{"mbid": "", "title": "teardrop", "artist": "massive attack"}]

    async def _gather():
        return await asyncio.gather(
            get_recommendations(seed, API_KEY, None, 0),
            get_recommendations(seed, API_KEY, None, 0.5),
            get_recommendations(seed, API_KEY, None, 1),
        )

    t_start = time.perf_counter()
    t0, t5, t1 = asyncio.run(_gather())
    print(
        f"\n[TIME] UserSim F (novelty gradient, 3x parallel): {time.perf_counter() - t_start:.2f}s"
    )
    return t0, t5, t1


# UserSim A - Mainstream synth-pop: "Blinding Lights" - The Weeknd


class TestUserSimA:
    def test_returns_results(self, synth_pop_tracks):
        if not API_KEY:
            return
        assert isinstance(synth_pop_tracks, list)

    def test_all_tracks_have_valid_shape(self, synth_pop_tracks):
        if not API_KEY or not synth_pop_tracks:
            return
        report = analyse_quality("Synth-pop (novelty=0)", synth_pop_tracks)
        print_quality(report, synth_pop_tracks)
        for t in synth_pop_tracks:
            assert_shape(t)

    def test_artist_cap_respected(self, synth_pop_tracks):
        if not API_KEY or not synth_pop_tracks:
            return
        assert_artist_cap(synth_pop_tracks)

    def test_at_most_10_tracks(self, synth_pop_tracks):
        if not API_KEY:
            return
        assert len(synth_pop_tracks) <= 10

    def test_no_track_has_relevance_zero(self, synth_pop_tracks):
        if not API_KEY or not synth_pop_tracks:
            return
        report = analyse_quality("Synth-pop (novelty=0)", synth_pop_tracks)
        assert report["tracks_with_zero_relevance"] == 0

    def test_relevance_spread_at_least_0_2(self, synth_pop_tracks):
        if not API_KEY or not synth_pop_tracks or len(synth_pop_tracks) < 3:
            return
        report = analyse_quality("Synth-pop (novelty=0)", synth_pop_tracks)
        assert report["relevance_spread"] >= 0.2


# UserSim B - Hip-hop: "HUMBLE." - Kendrick Lamar


class TestUserSimB:
    def test_returns_results(self, hip_hop_tracks):
        if not API_KEY:
            return
        assert isinstance(hip_hop_tracks, list)

    def test_all_tracks_have_valid_shape(self, hip_hop_tracks):
        if not API_KEY or not hip_hop_tracks:
            return
        report = analyse_quality("Hip-hop (novelty=0)", hip_hop_tracks)
        print_quality(report, hip_hop_tracks)
        for t in hip_hop_tracks:
            assert_shape(t)

    def test_artist_cap_respected(self, hip_hop_tracks):
        if not API_KEY or not hip_hop_tracks:
            return
        assert_artist_cap(hip_hop_tracks)

    def test_seed_artist_not_in_top_result(self, hip_hop_tracks):
        if not API_KEY or not hip_hop_tracks:
            return
        # seed track "humble" by "kendrick lamar" must not appear
        seed_in_results = any(
            "humble" in t.title.lower() and "kendrick" in t.artist.lower()
            for t in hip_hop_tracks
        )
        assert seed_in_results is False

    def test_avg_relevance_at_least_0_3(self, hip_hop_tracks):
        if not API_KEY or not hip_hop_tracks:
            return
        report = analyse_quality("Hip-hop (novelty=0)", hip_hop_tracks)
        assert report["avg_relevance"] >= 0.3


# UserSim C - Classic rock: "Stairway to Heaven" - Led Zeppelin


class TestUserSimC:
    def test_returns_results(self, classic_rock_tracks):
        if not API_KEY:
            return
        assert isinstance(classic_rock_tracks, list)

    def test_all_tracks_have_valid_shape(self, classic_rock_tracks):
        if not API_KEY or not classic_rock_tracks:
            return
        report = analyse_quality(
            "Classic rock (novelty=0)", classic_rock_tracks
        )
        print_quality(report, classic_rock_tracks)
        for t in classic_rock_tracks:
            assert_shape(t)

    def test_artist_cap_respected(self, classic_rock_tracks):
        if not API_KEY or not classic_rock_tracks:
            return
        assert_artist_cap(classic_rock_tracks)

    def test_at_least_5_unique_artists(self, classic_rock_tracks):
        if (
            not API_KEY
            or not classic_rock_tracks
            or len(classic_rock_tracks) < 5
        ):
            return
        report = analyse_quality(
            "Classic rock (novelty=0)", classic_rock_tracks
        )
        assert report["unique_artists"] >= 5


# UserSim D - Ultra-niche: "Alien Observer" - Grouper


class TestUserSimD:
    def test_returns_an_array(self, ultra_niche_tracks):
        if not API_KEY:
            return
        assert isinstance(ultra_niche_tracks, list)

    def test_all_tracks_have_valid_shape(self, ultra_niche_tracks):
        if not API_KEY or not ultra_niche_tracks:
            return
        report = analyse_quality(
            "Ultra-niche Grouper (novelty=0)", ultra_niche_tracks
        )
        print_quality(report, ultra_niche_tracks)
        for t in ultra_niche_tracks:
            assert_shape(t)

    def test_if_results_returned_artist_cap_respected(self, ultra_niche_tracks):
        if not API_KEY or not ultra_niche_tracks:
            return
        assert_artist_cap(ultra_niche_tracks)

    def test_if_results_returned_no_zero_relevance_tracks(
        self, ultra_niche_tracks
    ):
        if not API_KEY or not ultra_niche_tracks:
            return
        report = analyse_quality(
            "Ultra-niche Grouper (novelty=0)", ultra_niche_tracks
        )
        assert report["tracks_with_zero_relevance"] == 0


# UserSim E - Multi-seed indie: The National + Bon Iver


class TestUserSimE:
    def test_all_three_runs_return_arrays(self, multi_seed_tracks):
        if not API_KEY:
            return
        national, bon_iver, multi = multi_seed_tracks
        assert isinstance(national, list)
        assert isinstance(bon_iver, list)
        assert isinstance(multi, list)

    def test_artist_cap_respected_in_all_three(self, multi_seed_tracks):
        if not API_KEY:
            return
        national, bon_iver, multi = multi_seed_tracks
        if national:
            assert_artist_cap(national)
        if bon_iver:
            assert_artist_cap(bon_iver)
        if multi:
            assert_artist_cap(multi)

    def test_multi_seed_result_differs_from_both_single_seed_results(
        self, multi_seed_tracks
    ):
        if not API_KEY:
            return
        national, bon_iver, multi = multi_seed_tracks
        if not multi or not national or not bon_iver:
            return
        top1_n = national[0].mbid if national else None
        top1_b = bon_iver[0].mbid if bon_iver else None
        top1_m = multi[0].mbid if multi else None
        print(
            f"[QUALITY] top-1 mbids - National:{top1_n}  BonIver:{top1_b}  Multi:{top1_m}"
        )
        # Multi top result must differ from at least one of the single-seed tops
        assert not (top1_m == top1_n and top1_m == top1_b)

    def test_seed_artists_excluded_from_their_own_results(
        self, multi_seed_tracks
    ):
        if not API_KEY:
            return
        national, bon_iver, multi = multi_seed_tracks
        if national:
            has_national = any(
                t.title.lower() == "bloodbuzz ohio"
                and t.artist.lower() == "the national"
                for t in national
            )
            assert has_national is False
        if bon_iver:
            has_bon = any(
                t.title.lower() == "skinny love"
                and t.artist.lower() == "bon iver"
                for t in bon_iver
            )
            assert has_bon is False


# UserSim F - Novelty gradient: 0 vs 0.5 vs 1, "Teardrop" - Massive Attack


class TestUserSimF:
    def test_all_three_novelty_levels_return_arrays(
        self, novelty_gradient_tracks
    ):
        if not API_KEY:
            return
        t0, t5, t1 = novelty_gradient_tracks
        assert isinstance(t0, list)
        assert isinstance(t5, list)
        assert isinstance(t1, list)

    def test_novelty_0_5_avg_novelty_score_is_between_0_and_1(
        self, novelty_gradient_tracks
    ):
        if not API_KEY:
            return
        t0, t5, t1 = novelty_gradient_tracks
        if not t0 or not t5 or not t1:
            return

        def avg(arr):
            return sum(t.novelty_score for t in arr) / len(arr)

        n0, n5, n1 = avg(t0), avg(t5), avg(t1)
        print(
            f"[QUALITY] avg novelty: nov=0 => {n0:.3f}, nov=0.5 => {n5:.3f}, nov=1 => {n1:.3f}"
        )
        assert n5 >= n0
        assert n1 >= n5

    def test_novelty_0_5_avg_relevance_is_between_0_and_1(
        self, novelty_gradient_tracks
    ):
        if not API_KEY:
            return
        t0, t5, t1 = novelty_gradient_tracks
        if not t0 or not t5 or not t1:
            return

        def avg(arr):
            return sum(t.relevance_score for t in arr) / len(arr)

        r0, r5, r1 = avg(t0), avg(t5), avg(t1)
        print(
            f"[QUALITY] avg relevance: nov=0 => {r0:.3f}, nov=0.5 => {r5:.3f}, nov=1 => {r1:.3f}"
        )
        assert r5 <= r0 + 0.10  # may be slightly above due to pool differences
        assert r1 <= r5 + 0.10

    def test_artist_cap_respected_across_all_novelty_levels(
        self, novelty_gradient_tracks
    ):
        if not API_KEY:
            return
        t0, t5, t1 = novelty_gradient_tracks
        if t0:
            assert_artist_cap(t0)
        if t5:
            assert_artist_cap(t5)
        if t1:
            assert_artist_cap(t1)
