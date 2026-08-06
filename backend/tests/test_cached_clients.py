from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from caching.config import (
    NEGATIVE_TTL_S,
    TTL_ARTIST_MBID,
    TTL_RECORDING_MBID,
    TTL_STREAMING_LINKS,
)
from caching.keys import build_key
from recommendations.cached_clients import (
    NS_ARTIST_MBID,
    NS_ARTIST_POPULARITY,
    NS_RECORDING_MBID,
    NS_STREAMING,
    wrap_clients,
)
from recommendations.constants import recording_source
from recommendations.types import StreamingLinks

API_KEY = "secret-lastfm-key"


def _streaming_links(video_id="yt-1", lookup_failed=False):
    return StreamingLinks(
        apple_music="https://music.apple.com/x",
        preview="https://example.com/p.m4a",
        youtube_video_id=video_id,
        spotify="https://open.spotify.com/search/x",
        artwork={"small": "https://example.com/s.jpg"},
        lookup_failed=lookup_failed,
    )


def _unresolved_recording(mbid="m-1"):
    return {
        "mbid": mbid,
        "duration_ms": None,
        "album": None,
        "release_mbid": None,
        "release_date": None,
    }


def _resolved_recording(mbid="m-1"):
    return {
        "mbid": mbid,
        "duration_ms": 240000,
        "album": "OK Computer",
        "release_mbid": "rel-1",
        "release_date": "1997-05-21",
    }


@pytest.fixture
def stub_clients():
    return SimpleNamespace(
        fetch_tag_artists=AsyncMock(
            return_value=[{"name": "Radiohead", "mbid": "a-1"}]
        ),
        fetch_track_tags=AsyncMock(
            return_value=[{"name": "rock", "count": 100}]
        ),
        fetch_track_tags_only=AsyncMock(
            return_value=[{"name": "indie", "count": 50}]
        ),
        fetch_recording_tags=AsyncMock(
            return_value=[{"name": "alt", "count": 10}]
        ),
        fetch_top_recordings_for_artist=AsyncMock(
            return_value=[{"mbid": "r-1"}]
        ),
        resolve_artist_mbid=AsyncMock(return_value="artist-mbid-1"),
        resolve_recording_mbid=AsyncMock(return_value={"mbid": "rec-1"}),
        fetch_artist_popularity=AsyncMock(return_value={"a-1": 500}),
        get_streaming_links=AsyncMock(return_value=_streaming_links()),
    )


@pytest.fixture
def cached(stub_clients, async_cache_enabled):
    return wrap_clients(stub_clients)


CALLS = {
    "fetch_tag_artists": (("rock", 1, 30, API_KEY), {}),
    "fetch_track_tags": (("Creep", "Radiohead", API_KEY, "mbid-1"), {}),
    "fetch_track_tags_only": (("Creep", "Radiohead", API_KEY, "mbid-1"), {}),
    "fetch_recording_tags": (("mbid-1",), {}),
    "fetch_top_recordings_for_artist": (("a-1", "Radiohead", 5, API_KEY), {}),
    "resolve_artist_mbid": (("Radiohead",), {}),
    "resolve_recording_mbid": (("mbid-1", "Creep", "Radiohead"), {}),
    "get_streaming_links": (("Radiohead", "Creep"), {}),
}


class TestReadThrough:
    @pytest.mark.parametrize("method", sorted(CALLS))
    async def test_second_call_is_served_from_cache(
        self, cached, stub_clients, method
    ):
        args, kwargs = CALLS[method]
        first = await getattr(cached, method)(*args, **kwargs)
        second = await getattr(cached, method)(*args, **kwargs)

        assert getattr(stub_clients, method).call_count == 1
        assert first == second

    @pytest.mark.parametrize("method", sorted(CALLS))
    async def test_cached_value_matches_the_uncached_one(
        self, cached, stub_clients, method
    ):
        args, kwargs = CALLS[method]
        expected = await getattr(stub_clients, method)(*args, **kwargs)
        assert await getattr(cached, method)(*args, **kwargs) == expected

    async def test_different_arguments_do_not_share_an_entry(
        self, cached, stub_clients
    ):
        await cached.resolve_artist_mbid("Radiohead")
        await cached.resolve_artist_mbid("Nirvana")
        assert stub_clients.resolve_artist_mbid.call_count == 2

    async def test_cache_miss_still_calls_through(self, cached, stub_clients):
        await cached.fetch_recording_tags("mbid-1")
        stub_clients.fetch_recording_tags.assert_awaited_once_with("mbid-1")

    # With Redis down every call has to reach the real client, not fail
    async def test_works_uncached_when_redis_is_unavailable(self, stub_clients):
        cached = wrap_clients(stub_clients)
        assert await cached.resolve_artist_mbid("Radiohead") == "artist-mbid-1"
        assert await cached.resolve_artist_mbid("Radiohead") == "artist-mbid-1"
        assert stub_clients.resolve_artist_mbid.call_count == 2

    def test_wrapping_leaves_the_original_namespace_untouched(
        self, stub_clients
    ):
        original = stub_clients.resolve_artist_mbid
        wrap_clients(stub_clients)
        assert stub_clients.resolve_artist_mbid is original

    def test_unknown_attributes_are_carried_across(self, stub_clients):
        stub_clients.some_extra = "kept"
        assert wrap_clients(stub_clients).some_extra == "kept"


class TestFalsyResults:
    async def test_empty_string_result_is_still_a_cache_hit(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            resolve_artist_mbid=AsyncMock(return_value="")
        )
        cached = wrap_clients(clients)
        assert await cached.resolve_artist_mbid("Nobody") == ""
        assert await cached.resolve_artist_mbid("Nobody") == ""
        assert clients.resolve_artist_mbid.call_count == 1

    async def test_empty_list_result_is_still_a_cache_hit(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            fetch_recording_tags=AsyncMock(return_value=[])
        )
        cached = wrap_clients(clients)
        await cached.fetch_recording_tags("mbid-1")
        await cached.fetch_recording_tags("mbid-1")
        assert clients.fetch_recording_tags.call_count == 1

    # An empty result gets the short TTL because it may just mean it's rate
    # limited and a failure must not be cached for 30 days
    async def test_empty_result_gets_the_short_negative_ttl(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            resolve_artist_mbid=AsyncMock(return_value="")
        )
        await wrap_clients(clients).resolve_artist_mbid("Nobody")

        ttl = await async_cache_enabled._get_client().ttl(
            build_key(NS_ARTIST_MBID, "Nobody")
        )
        assert 0 < ttl <= NEGATIVE_TTL_S

    async def test_found_result_gets_the_long_positive_ttl(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            resolve_artist_mbid=AsyncMock(return_value="mbid-1")
        )
        await wrap_clients(clients).resolve_artist_mbid("Radiohead")

        ttl = await async_cache_enabled._get_client().ttl(
            build_key(NS_ARTIST_MBID, "Radiohead")
        )
        assert ttl > NEGATIVE_TTL_S
        assert ttl <= TTL_ARTIST_MBID


class TestApiKeyIsNotCached:
    @pytest.mark.parametrize(
        "method",
        [
            "fetch_tag_artists",
            "fetch_track_tags",
            "fetch_track_tags_only",
            "fetch_top_recordings_for_artist",
        ],
    )
    async def test_api_key_never_appears_in_a_key(
        self, cached, async_cache_enabled, method
    ):
        args, kwargs = CALLS[method]
        await getattr(cached, method)(*args, **kwargs)

        keys = await async_cache_enabled._get_client().keys("*")
        assert keys
        assert not any(API_KEY in key for key in keys)

    async def test_a_rotated_api_key_still_hits_the_same_entry(
        self, cached, stub_clients
    ):
        await cached.fetch_tag_artists("rock", 1, 30, "old-key")
        await cached.fetch_tag_artists("rock", 1, 30, "new-key")
        assert stub_clients.fetch_tag_artists.call_count == 1


class TestStreamingLinks:
    async def test_returns_a_dataclass_on_a_cache_hit(self, cached):
        await cached.get_streaming_links("Radiohead", "Creep")
        result = await cached.get_streaming_links("Radiohead", "Creep")
        assert isinstance(result, StreamingLinks)

    async def test_every_field_survives_the_round_trip(
        self, cached, stub_clients
    ):
        expected = stub_clients.get_streaming_links.return_value
        await cached.get_streaming_links("Radiohead", "Creep")
        cached_result = await cached.get_streaming_links("Radiohead", "Creep")

        assert cached_result.apple_music == expected.apple_music
        assert cached_result.preview == expected.preview
        assert cached_result.youtube_video_id == expected.youtube_video_id
        assert cached_result.spotify == expected.spotify
        assert cached_result.artwork == expected.artwork

    async def test_result_with_no_video_id_gets_the_full_ttl(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            get_streaming_links=AsyncMock(
                return_value=_streaming_links(video_id=None)
            )
        )
        await wrap_clients(clients).get_streaming_links("Nobody", "Nothing")

        ttl = await async_cache_enabled._get_client().ttl(
            build_key(NS_STREAMING, "Nobody", "Nothing")
        )
        assert ttl > NEGATIVE_TTL_S
        assert ttl <= TTL_STREAMING_LINKS

    async def test_a_failed_lookup_gets_the_short_negative_ttl(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            get_streaming_links=AsyncMock(
                return_value=_streaming_links(video_id=None, lookup_failed=True)
            )
        )
        await wrap_clients(clients).get_streaming_links("Nobody", "Nothing")

        ttl = await async_cache_enabled._get_client().ttl(
            build_key(NS_STREAMING, "Nobody", "Nothing")
        )
        assert 0 < ttl <= NEGATIVE_TTL_S

    async def test_the_failure_flag_is_not_stored(self, async_cache_enabled):
        clients = SimpleNamespace(
            get_streaming_links=AsyncMock(
                return_value=_streaming_links(lookup_failed=True)
            )
        )
        cached = wrap_clients(clients)
        await cached.get_streaming_links("Radiohead", "Creep")
        result = await cached.get_streaming_links("Radiohead", "Creep")

        assert result.lookup_failed is False


class TestRecordingResolution:
    async def test_an_unresolved_recording_gets_the_short_negative_ttl(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            resolve_recording_mbid=AsyncMock(
                return_value=_unresolved_recording()
            )
        )
        await wrap_clients(clients).resolve_recording_mbid(
            "m-1", "Creep", "Radiohead"
        )

        ttl = await async_cache_enabled._get_client().ttl(
            build_key(
                NS_RECORDING_MBID,
                recording_source(),
                "m-1",
                "Creep",
                "Radiohead",
            )
        )
        assert 0 < ttl <= NEGATIVE_TTL_S

    async def test_a_resolved_recording_gets_the_long_positive_ttl(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            resolve_recording_mbid=AsyncMock(return_value=_resolved_recording())
        )
        await wrap_clients(clients).resolve_recording_mbid(
            "m-1", "Creep", "Radiohead"
        )

        ttl = await async_cache_enabled._get_client().ttl(
            build_key(
                NS_RECORDING_MBID,
                recording_source(),
                "m-1",
                "Creep",
                "Radiohead",
            )
        )
        assert ttl > NEGATIVE_TTL_S
        assert ttl <= TTL_RECORDING_MBID

    async def test_a_partially_resolved_recording_counts_as_resolved(
        self, async_cache_enabled
    ):
        partial = _unresolved_recording() | {"album": "Pablo Honey"}
        clients = SimpleNamespace(
            resolve_recording_mbid=AsyncMock(return_value=partial)
        )
        await wrap_clients(clients).resolve_recording_mbid(
            "m-1", "Creep", "Radiohead"
        )

        ttl = await async_cache_enabled._get_client().ttl(
            build_key(
                NS_RECORDING_MBID,
                recording_source(),
                "m-1",
                "Creep",
                "Radiohead",
            )
        )
        assert ttl > NEGATIVE_TTL_S

    async def test_an_unresolved_recording_is_still_returned_to_the_caller(
        self, async_cache_enabled
    ):
        unresolved = _unresolved_recording()
        clients = SimpleNamespace(
            resolve_recording_mbid=AsyncMock(return_value=unresolved)
        )
        cached = wrap_clients(clients)

        assert (
            await cached.resolve_recording_mbid("m-1", "Creep", "Radiohead")
            == unresolved
        )
        assert (
            await cached.resolve_recording_mbid("m-1", "Creep", "Radiohead")
            == unresolved
        )
        assert clients.resolve_recording_mbid.call_count == 1


class TestArtistPopularity:
    async def test_second_identical_batch_is_fully_cached(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            fetch_artist_popularity=AsyncMock(
                return_value={"a-1": 10, "a-2": 20}
            )
        )
        cached = wrap_clients(clients)
        assert await cached.fetch_artist_popularity(["a-1", "a-2"]) == {
            "a-1": 10,
            "a-2": 20,
        }
        assert await cached.fetch_artist_popularity(["a-1", "a-2"]) == {
            "a-1": 10,
            "a-2": 20,
        }
        assert clients.fetch_artist_popularity.call_count == 1

    async def test_only_the_missing_mbids_are_fetched(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            fetch_artist_popularity=AsyncMock(
                side_effect=[{"a-1": 10}, {"a-2": 20}]
            )
        )
        cached = wrap_clients(clients)
        await cached.fetch_artist_popularity(["a-1"])
        result = await cached.fetch_artist_popularity(["a-1", "a-2"])

        assert result == {"a-1": 10, "a-2": 20}
        assert clients.fetch_artist_popularity.call_args_list[1].args[0] == [
            "a-2"
        ]

    async def test_batch_ordering_does_not_affect_hits(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            fetch_artist_popularity=AsyncMock(
                return_value={"a-1": 10, "a-2": 20}
            )
        )
        cached = wrap_clients(clients)
        await cached.fetch_artist_popularity(["a-1", "a-2"])
        await cached.fetch_artist_popularity(["a-2", "a-1"])
        assert clients.fetch_artist_popularity.call_count == 1

    # An MBID ListenBrainz has no data for is remembered as absent, so the next
    # run does not re-ask, but only briefly in case the gap was an outage
    async def test_mbid_with_no_data_is_negatively_cached(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            fetch_artist_popularity=AsyncMock(return_value={})
        )
        cached = wrap_clients(clients)
        assert await cached.fetch_artist_popularity(["a-missing"]) == {}
        assert await cached.fetch_artist_popularity(["a-missing"]) == {}
        assert clients.fetch_artist_popularity.call_count == 1

        ttl = await async_cache_enabled._get_client().ttl(
            build_key(NS_ARTIST_POPULARITY, "a-missing")
        )
        assert 0 < ttl <= NEGATIVE_TTL_S

    # Returning {} without calling through loses nothing, the real client makes
    # the same check before its POST and would return {} too
    @pytest.mark.parametrize("mbids", [[], ["", None]])
    async def test_no_valid_mbids_short_circuits(
        self, async_cache_enabled, mbids
    ):
        clients = SimpleNamespace(
            fetch_artist_popularity=AsyncMock(return_value={})
        )
        cached = wrap_clients(clients)
        assert await cached.fetch_artist_popularity(mbids) == {}
        clients.fetch_artist_popularity.assert_not_awaited()

    async def test_valid_mbids_alongside_falsy_ones_are_still_fetched(
        self, async_cache_enabled
    ):
        clients = SimpleNamespace(
            fetch_artist_popularity=AsyncMock(return_value={"a-1": 10})
        )
        cached = wrap_clients(clients)
        assert await cached.fetch_artist_popularity(["", "a-1", None]) == {
            "a-1": 10
        }
        assert clients.fetch_artist_popularity.call_args.args[0] == ["a-1"]


class TestPipelineIntegration:
    @pytest.fixture
    def counting_clients(self):
        from tests.test_pipeline import make_clients

        base = make_clients()
        calls = []

        # Records every external call the pipeline makes, by method name
        counted = SimpleNamespace()
        for name in dir(base):
            if name.startswith("_"):
                continue
            attr = getattr(base, name)

            def make_counter(fn, fn_name):
                async def counter(*args, **kwargs):
                    calls.append(fn_name)
                    return await fn(*args, **kwargs)

                return counter

            setattr(counted, name, make_counter(attr, name))
        return counted, calls

    async def _run(self, clients):
        from recommendations.pipeline import run_pipeline
        from recommendations.types import Seed

        return await run_pipeline(
            [
                Seed(
                    mbid="seed-1",
                    title="Sometimes",
                    artist="My Bloody Valentine",
                )
            ],
            API_KEY,
            None,
            0.5,
            clients,
        )

    # Guards against the wrapper silently changing what the pipeline receives
    async def test_wrapped_run_returns_the_same_tracks(
        self, counting_clients, async_cache_enabled
    ):
        clients, _ = counting_clients
        uncached = await self._run(clients)
        cached = await self._run(wrap_clients(clients))

        assert [t.mbid for t in cached] == [t.mbid for t in uncached]

    async def test_second_run_makes_no_external_calls(
        self, counting_clients, async_cache_enabled
    ):
        clients, calls = counting_clients
        cached = wrap_clients(clients)

        await self._run(cached)
        assert calls, "the first run should hit the real clients"
        calls.clear()
        await self._run(cached)

        assert calls == [], f"second run still called: {sorted(set(calls))}"

    async def test_accepts_a_class_based_clients_object(
        self, async_cache_enabled
    ):
        from tests.test_pipeline import make_clients

        tracks = await self._run(wrap_clients(make_clients()))
        assert len(tracks) > 0


class TestRecordingSourceIsolation:
    async def test_switching_source_does_not_reuse_the_entry(
        self, async_cache_enabled, monkeypatch
    ):
        clients = SimpleNamespace(
            fetch_top_recordings_for_artist=AsyncMock(
                return_value=[{"mbid": "r-1"}]
            )
        )
        cached = wrap_clients(clients)

        monkeypatch.setenv("RECORDING_SOURCE", "listenbrainz")
        await cached.fetch_top_recordings_for_artist(
            "a-1", "Radiohead", 5, API_KEY
        )
        monkeypatch.setenv("RECORDING_SOURCE", "lastfm")
        await cached.fetch_top_recordings_for_artist(
            "a-1", "Radiohead", 5, API_KEY
        )

        assert clients.fetch_top_recordings_for_artist.call_count == 2

    async def test_same_source_reuses_the_entry(
        self, async_cache_enabled, monkeypatch
    ):
        clients = SimpleNamespace(
            resolve_recording_mbid=AsyncMock(
                return_value=_resolved_recording("r-1")
            )
        )
        cached = wrap_clients(clients)

        monkeypatch.setenv("RECORDING_SOURCE", "lastfm")
        await cached.resolve_recording_mbid("m-1", "Creep", "Radiohead")
        await cached.resolve_recording_mbid("m-1", "Creep", "Radiohead")

        assert clients.resolve_recording_mbid.call_count == 1

    # The wrapper and the pipeline have to agree on the source name
    async def test_an_invalid_source_shares_the_default_namespace(
        self, async_cache_enabled, monkeypatch
    ):
        clients = SimpleNamespace(
            fetch_top_recordings_for_artist=AsyncMock(
                return_value=[{"mbid": "r-1"}]
            )
        )
        cached = wrap_clients(clients)

        monkeypatch.setenv("RECORDING_SOURCE", "listenbrainz")
        await cached.fetch_top_recordings_for_artist(
            "a-1", "Radiohead", 5, API_KEY
        )
        monkeypatch.setenv("RECORDING_SOURCE", "listenbrians")  # typo
        await cached.fetch_top_recordings_for_artist(
            "a-1", "Radiohead", 5, API_KEY
        )

        assert clients.fetch_top_recordings_for_artist.call_count == 1
