import json
import logging

import pytest

from evaluation import seed_resolution as resolution
from evaluation.seed_resolution import (
    ResolutionIncomplete,
    apply_resolutions,
    artist_matches,
    pick_mbid,
    resolve_catalogue,
    resolve_seed,
    unique_seeds,
)


def seed(title="Creep", artist="Radiohead", track_id="spotify:track:1"):
    return {
        "recording_mbid": "",
        "title": title,
        "artist": artist,
        "artist_mbids": [],
        "track_id": track_id,
    }


def result(mbid, title="Creep", artist="Radiohead"):
    return {"mbid": mbid, "title": title, "artist": artist}


async def no_sleep(_seconds):
    return None


class TestArtistMatches:
    @pytest.mark.parametrize(
        "wanted, credited, expected",
        [
            ("Radiohead", "Radiohead", True),
            ("radiohead", "RADIOHEAD", True),
            ("Jay-Z", "JAY-Z & Kanye West", True),
            ("Drake", "Drake feat. Rihanna", True),
            ("Calvin Harris", "Calvin Harris, Dua Lipa", True),
            ("Simon & Garfunkel", "Simon and Garfunkel", True),
            ("Simon & Garfunkel", "Simon & Garfunkel", True),
            ("Radiohead", "Radiohead Tribute Band", False),
            ("Radio", "Radiohead", False),
            ("Kanye West", "JAY-Z & Kanye West", False),
            ("", "Anyone", False),
        ],
    )
    def test_folds_case_and_accepts_leading_credits(self, wanted, credited, expected):
        assert artist_matches(wanted, credited) is expected


class TestPickMbid:
    def test_takes_the_first_matching_result(self):
        results = [
            result("wrong-artist", artist="Cover Band"),
            result("right"),
            result("later"),
        ]
        assert pick_mbid(seed(), results) == "right"

    def test_accepts_title_variants(self):
        results = [result("m1", title="Creep - Remastered")]
        assert pick_mbid(seed(), results) == "m1"

    def test_returns_empty_without_a_match(self):
        assert pick_mbid(seed(), [result("m1", title="Karma Police")]) == ""

    def test_skips_results_without_an_mbid(self):
        assert pick_mbid(seed(), [result(""), result("m2")]) == "m2"


class TestResolveSeed:
    async def test_returns_the_matching_mbid(self):
        async def search(title, artist):
            return [result("m1")]

        assert await resolve_seed(seed(), search, no_sleep) == "m1"

    async def test_retries_a_search_that_logged_a_failure(self):
        calls = []

        async def search(title, artist):
            calls.append(title)
            if len(calls) == 1:
                logging.getLogger("clients.musicbrainz").warning("MB search HTTP 503")
                return []
            return [result("m1")]

        assert await resolve_seed(seed(), search, no_sleep) == "m1"
        assert len(calls) == 2

    async def test_gives_up_after_repeated_failures(self):
        async def search(title, artist):
            logging.getLogger("clients.musicbrainz").warning("MB search HTTP 503")
            return []

        with pytest.raises(ResolutionIncomplete):
            await resolve_seed(seed(), search, no_sleep)

    async def test_a_clean_empty_search_is_unresolved_not_failed(self):
        async def search(title, artist):
            return []

        assert await resolve_seed(seed(), search, no_sleep) == ""


def catalogue(tmp_path, cases):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return path


def case(case_id, *seeds):
    return {"case_id": case_id, "seeds": list(seeds), "held_out": []}


class TestCatalogueResolution:
    def test_unique_seeds_collapses_shared_seeds(self):
        cases = [case("a-1seed", seed()), case("a-2seed", seed(), seed("X", "Y", "t2"))]
        assert len(unique_seeds(cases)) == 2

    def test_apply_updates_every_case_using_the_seed(self):
        cases = [case("a-1seed", seed()), case("a-2seed", seed())]
        apply_resolutions(cases, {"spotify:track:1": "m1"})
        assert [c["seeds"][0]["recording_mbid"] for c in cases] == ["m1", "m1"]

    async def test_writes_mbids_and_a_summary(self, tmp_path):
        path = catalogue(
            tmp_path,
            [case("a-1seed", seed()), case("b-1seed", seed("Nope", "Nobody", "t9"))],
        )

        async def search(title, artist):
            return [result("m1")] if title == "Creep" else []

        summary = await resolve_catalogue(path, search, no_sleep)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["cases"][0]["seeds"][0]["recording_mbid"] == "m1"
        assert summary["resolved"] == 1
        assert summary["unresolved"] == ["Nobody - Nope"]

    async def test_resumes_without_searching_resolved_seeds_again(self, tmp_path):
        path = catalogue(tmp_path, [case("a-1seed", seed())])

        async def search(title, artist):
            return [result("m1")]

        await resolve_catalogue(path, search, no_sleep)

        async def refuse(title, artist):
            raise AssertionError("an already resolved seed must not be searched")

        summary = await resolve_catalogue(path, refuse, no_sleep)
        assert summary["resolved"] == 1

    async def test_keeps_progress_when_a_search_keeps_failing(self, tmp_path):
        path = catalogue(
            tmp_path, [case("a-1seed", seed()), case("b-1seed", seed("Bad", "X", "t2"))]
        )

        async def search(title, artist):
            if title == "Bad":
                logging.getLogger("clients.musicbrainz").warning("MB search HTTP 503")
                return []
            return [result("m1")]

        with pytest.raises(ResolutionIncomplete):
            await resolve_catalogue(path, search, no_sleep)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["seed_resolution"]["by_seed"] == {"spotify:track:1": "m1"}
        assert resolution.seed_key(seed("Bad", "X", "t2")) not in saved[
            "seed_resolution"
        ]["by_seed"]
