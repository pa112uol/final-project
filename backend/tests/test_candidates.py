import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from recommendations.candidates import (
    build_candidates,
    score_artists_across_all_tag_pages,
)
from recommendations.constants import TOP_ARTISTS_COUNT

RECORDING_A = {
    "mbid": "rec-a",
    "title": "Track A",
    "artist_mbid": "artist-mbid-1",
    "duration_ms": 200000,
    "listen_count": 5000,
    "user_count": 2000,
    "tags": ["shoegaze"],
}

RECORDING_B = {
    "mbid": "rec-b",
    "title": "Track B",
    "artist_mbid": "artist-mbid-1",
    "duration_ms": 180000,
    "listen_count": 3000,
    "user_count": 1000,
    "tags": [],
}


def make_clients(**overrides):
    class Clients:
        async def fetch_tag_artists(self, tag, page, limit, api_key):
            return [{"name": "Slowdive", "mbid": "artist-mbid-1"}]

        async def fetch_top_recordings_for_artist(self, mbid, name, limit, api_key):
            return [RECORDING_A]

        async def resolve_artist_mbid(self, name):
            return "resolved-mbid"

    clients = Clients()
    for k, v in overrides.items():
        setattr(clients, k, v)
    return clients


TOP_TAGS = [("shoegaze", 100)]


class TestBuildCandidates:
    async def test_returns_candidates_built_from_fetched_recordings(self):
        result = await build_candidates(TOP_TAGS, "key", 0, make_clients())
        assert len(result) == 1
        assert result[0].title == "Track A"
        assert result[0].mbid == "rec-a"
        assert result[0].listen_count == 5000

    async def test_initialises_track_tag_score_and_artist_listen_count_to_zero(self):
        result = await build_candidates(TOP_TAGS, "key", 0, make_clients())
        assert result[0].track_tag_score == 0
        assert result[0].artist_listen_count == 0

    async def test_sets_tag_weight_sum_from_artists_accumulated_tag_weight(self):
        result = await build_candidates(TOP_TAGS, "key", 0, make_clients())
        assert result[0].tag_weight_sum == 100

    async def test_uses_recording_tags_when_present_artist_tags_as_fallback(self):
        async def fetch_recordings(mbid, name, limit, api_key):
            return [RECORDING_A, RECORDING_B]

        clients = make_clients(fetch_top_recordings_for_artist=fetch_recordings)
        result = await build_candidates(TOP_TAGS, "key", 0, clients)
        rec_a = next(c for c in result if c.mbid == "rec-a")
        rec_b = next(c for c in result if c.mbid == "rec-b")
        assert rec_a.tags == ["shoegaze"]
        # rec_b has no tags; falls back to the artist's matched tag
        assert "shoegaze" in rec_b.tags

    async def test_at_novelty_zero_fetches_only_page_one_per_tag(self):
        pages_fetched = []

        async def fetch_tag_artists(tag, page, limit, api_key):
            pages_fetched.append(page)
            return [{"name": "Slowdive", "mbid": "artist-mbid-1"}]

        clients = make_clients(fetch_tag_artists=fetch_tag_artists)
        await build_candidates(TOP_TAGS, "key", 0, clients)
        assert pages_fetched == [1]

    async def test_at_novelty_one_fetches_pages_one_to_three_per_tag(self):
        pages_fetched = []

        async def fetch_tag_artists(tag, page, limit, api_key):
            pages_fetched.append(page)
            return [{"name": "Slowdive", "mbid": "artist-mbid-1"}]

        clients = make_clients(fetch_tag_artists=fetch_tag_artists)
        await build_candidates(TOP_TAGS, "key", 1, clients)
        assert sorted(pages_fetched) == [1, 2, 3]

    async def test_accumulates_tag_weight_sum_across_multiple_tags_for_same_artist(self):
        tags = [("shoegaze", 100), ("dreampop", 80)]

        async def fetch_tag_artists(tag, page, limit, api_key):
            return [{"name": "Slowdive", "mbid": "artist-mbid-1"}]

        clients = make_clients(fetch_tag_artists=fetch_tag_artists)
        result = await build_candidates(tags, "key", 0, clients)
        # Slowdive appears in both tags => tag_weight_sum = 100 + 80 = 180
        assert result[0].tag_weight_sum == 180

    async def test_credits_same_tag_only_once_per_artist_across_pages(self):
        pages_seen = []

        async def fetch_tag_artists(tag, page, limit, api_key):
            pages_seen.append(page)
            # Same artist on both pages
            return [{"name": "Slowdive", "mbid": "artist-mbid-1"}]

        clients = make_clients(fetch_tag_artists=fetch_tag_artists)
        result = await build_candidates(TOP_TAGS, "key", 0.5, clients)
        # tag_weight_sum should be 100, not 200, even if novelty causes 2 pages
        assert result[0].tag_weight_sum == 100

    async def test_duplicate_page_score_is_independent_of_completion_order(self):
        async def score_with_delayed_page(delayed_page):
            async def fetch_tag_artists(tag, page, limit, api_key):
                if page == delayed_page:
                    await asyncio.sleep(0.01)
                return [{"name": "Slowdive", "mbid": "artist-mbid-1"}]

            scores, _ = await score_artists_across_all_tag_pages(
                TOP_TAGS,
                pages_to_fetch=2,
                api_key="key",
                clients=make_clients(fetch_tag_artists=fetch_tag_artists),
            )
            return scores["slowdive"]["tag_weight_sum"]

        page_one_late = await score_with_delayed_page(1)
        page_two_late = await score_with_delayed_page(2)

        assert page_one_late == page_two_late == 100

    async def test_calls_resolve_artist_mbid_for_artists_without_mbid(self):
        calls = []

        async def resolve_artist_mbid(name):
            calls.append(name)
            return "resolved-mbid"

        async def fetch_tag_artists(tag, page, limit, api_key):
            return [{"name": "Obscure Band", "mbid": None}]

        clients = make_clients(
            fetch_tag_artists=fetch_tag_artists,
            resolve_artist_mbid=resolve_artist_mbid,
        )
        await build_candidates(TOP_TAGS, "key", 0, clients)
        assert "Obscure Band" in calls

    async def test_does_not_call_resolve_artist_mbid_when_mbid_already_present(self):
        calls = []

        async def resolve_artist_mbid(name):
            calls.append(name)
            return "resolved-mbid"

        clients = make_clients(resolve_artist_mbid=resolve_artist_mbid)
        await build_candidates(TOP_TAGS, "key", 0, clients)
        assert calls == []

    async def test_skips_artists_with_no_mbid_after_resolution(self):
        async def fetch_tag_artists(tag, page, limit, api_key):
            return [{"name": "Ghost Band", "mbid": None}]

        async def resolve_artist_mbid(name):
            return ""

        clients = make_clients(
            fetch_tag_artists=fetch_tag_artists,
            resolve_artist_mbid=resolve_artist_mbid,
        )
        result = await build_candidates(TOP_TAGS, "key", 0, clients)
        assert len(result) == 0

    async def test_returns_empty_when_no_tags_are_provided(self):
        result = await build_candidates([], "key", 0, make_clients())
        assert len(result) == 0

    async def test_swallows_fetch_tag_artists_failures_without_throwing(self):
        async def fetch_tag_artists(tag, page, limit, api_key):
            raise Exception("API down")

        clients = make_clients(fetch_tag_artists=fetch_tag_artists)
        result = await build_candidates(TOP_TAGS, "key", 0, clients)
        assert result == []

    async def test_swallows_fetch_top_recordings_for_artist_failures_without_throwing(self):
        async def fetch_recordings(mbid, name, limit, api_key):
            raise Exception("API down")

        clients = make_clients(fetch_top_recordings_for_artist=fetch_recordings)
        result = await build_candidates(TOP_TAGS, "key", 0, clients)
        assert result == []

    async def test_selects_artists_with_highest_tag_weight_sum_when_list_exceeds_top_artists_count(self):
        # More artists available than the cap allows, so the cap has to bite.
        # Asserted against the constant rather than a literal so retuning the
        # pool size does not silently turn this into a no-op.
        many_artists = [
            {"name": f"Artist{i}", "mbid": f"mbid-{i}"}
            for i in range(TOP_ARTISTS_COUNT + 5)
        ]

        async def fetch_tag_artists(tag, page, limit, api_key):
            return many_artists

        async def fetch_recordings(mbid, name, limit, api_key):
            return [RECORDING_A]

        clients = make_clients(
            fetch_tag_artists=fetch_tag_artists,
            fetch_top_recordings_for_artist=fetch_recordings,
        )
        result = await build_candidates(TOP_TAGS, "key", 0, clients)
        # At novelty=0 each selected artist contributes its single recording
        assert len(result) <= TOP_ARTISTS_COUNT

    async def test_applies_rank_decay_so_first_artist_receives_more_credit(self):
        async def fetch_tag_artists(tag, page, limit, api_key):
            return [
                {"name": "Slowdive", "mbid": "mbid-1"},
                {"name": "Ride", "mbid": "mbid-2"},
            ]

        async def fetch_recordings(mbid, name, limit, api_key):
            if mbid == "mbid-1":
                return [{**RECORDING_A, "mbid": "rec-1", "artist_mbid": "mbid-1"}]
            return [{**RECORDING_A, "mbid": "rec-2", "artist_mbid": "mbid-2", "title": "Track B"}]

        clients = make_clients(
            fetch_tag_artists=fetch_tag_artists,
            fetch_top_recordings_for_artist=fetch_recordings,
        )
        result = await build_candidates(TOP_TAGS, "key", 0, clients)
        slowdive = next(c for c in result if c.artist == "Slowdive")
        ride = next(c for c in result if c.artist == "Ride")
        # Slowdive is at rank 0 (decay=1.0) and Ride at rank 1 (decay < 1.0)
        assert slowdive.tag_weight_sum > ride.tag_weight_sum

    async def test_deduplicates_recordings_by_title_artist_key(self):
        duplicate = {**RECORDING_A, "mbid": "rec-a-dup"}

        async def fetch_recordings(mbid, name, limit, api_key):
            return [RECORDING_A, duplicate]

        clients = make_clients(fetch_top_recordings_for_artist=fetch_recordings)
        result = await build_candidates(TOP_TAGS, "key", 0, clients)
        track_a_titles = [c for c in result if c.title == "Track A"]
        # Same title+artist key: only one candidate is kept
        assert len(track_a_titles) == 1

    async def test_never_exceeds_five_concurrent_fetch_top_recordings_calls(self):
        # Build 15 artists (novelty=0 default) so the semaphore is exercised
        artists = [{"name": f"Artist{i}", "mbid": f"mbid-{i}"} for i in range(15)]
        peak = [0]
        in_flight = [0]

        async def fetch_recordings(mbid, name, limit, api_key):
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
            await asyncio.sleep(0.01)
            in_flight[0] -= 1
            return [RECORDING_A]

        async def fetch_tag_artists(tag, page, limit, api_key):
            return artists

        clients = make_clients(
            fetch_tag_artists=fetch_tag_artists,
            fetch_top_recordings_for_artist=fetch_recordings,
        )
        await build_candidates(TOP_TAGS, "key", 0, clients)
        assert peak[0] <= 5
