import httpx
import pytest

from evaluation import playlist_catalogue as catalogue
from evaluation.playlist_catalogue import (
    CatalogueIncomplete,
    Playlist,
    PlaylistTrack,
    RateLimiter,
    ResponseCache,
    backoff_seconds,
    build_cases,
    case_from_dict,
    case_to_dict,
    fetch_json,
    held_out_tracks,
    is_eligible,
    is_generated,
    max_artist_share,
    parse_playlist,
    parse_playlist_track,
    discover_users,
    pick_playlists,
    sampling_order,
    user_path,
)


def make_track(index: int, artist: str | None = None) -> PlaylistTrack:
    name = artist or f"Artist {index}"
    return PlaylistTrack(
        recording_mbid=f"rec-{index}",
        title=f"Song {index}",
        artist=name,
        artist_mbids=(f"artist-{name}",),
    )


def make_playlist(
    tracks, title="Road trip", creator="alice", mbid="pl-0001"
) -> Playlist:
    return Playlist(
        playlist_mbid=mbid, title=title, creator=creator, tracks=tuple(tracks)
    )


def raw_track(recording="rec-1", title="Song", creator="Band", artists=None):
    return {
        "identifier": [f"https://musicbrainz.org/recording/{recording}"],
        "title": title,
        "creator": creator,
        "extension": {
            catalogue.TRACK_EXTENSION: {
                "artist_identifiers": [
                    f"https://musicbrainz.org/artist/{mbid}"
                    for mbid in (artists or ["band-mbid"])
                ]
            }
        },
    }


@pytest.fixture
def varied_playlist():
    return make_playlist([make_track(i) for i in range(12)])


class TestParsePlaylistTrack:
    def test_reads_recording_and_artist_mbids(self):
        track = parse_playlist_track(raw_track(artists=["a1", "a2"]))
        assert track == PlaylistTrack("rec-1", "Song", "Band", ("a1", "a2"))

    def test_accepts_a_single_string_identifier(self):
        raw = raw_track()
        raw["identifier"] = "https://musicbrainz.org/recording/rec-9"
        assert parse_playlist_track(raw).recording_mbid == "rec-9"

    @pytest.mark.parametrize(
        "change",
        [
            {"identifier": []},
            {"identifier": ["https://example.com/track/1"]},
            {"title": ""},
            {"creator": "  "},
        ],
    )
    def test_rejects_tracks_missing_required_fields(self, change):
        raw = {**raw_track(), **change}
        assert parse_playlist_track(raw) is None

    def test_missing_extension_gives_no_artist_mbids(self):
        raw = raw_track()
        del raw["extension"]
        assert parse_playlist_track(raw).artist_mbids == ()


class TestParsePlaylist:
    def test_drops_unusable_tracks_and_reads_header(self):
        raw = {
            "identifier": "https://listenbrainz.org/playlist/pl-42",
            "title": "Mix",
            "creator": "bob",
            "track": [raw_track(), {"title": "no id", "creator": "x"}],
        }
        playlist = parse_playlist(raw)
        assert playlist.playlist_mbid == "pl-42"
        assert playlist.creator == "bob"
        assert len(playlist.tracks) == 1


class TestIsGenerated:
    @pytest.mark.parametrize(
        "title, creator, extension",
        [
            ("Daily Jams for rob", "rob", {}),
            ("LB Radio for tag shoegaze", "rob", {}),
            ("Copy of my mix", "rob", {}),
            ("Anything", "troi-bot", {}),
            ("Anything", "rob", {"algorithm_metadata": {}}),
            ("Anything", "rob", {"additional_metadata": {"algorithm_metadata": {}}}),
            ("Anything", "rob", {"copied_from": "pl-other"}),
        ],
    )
    def test_flags_recommender_output(self, title, creator, extension):
        playlist = Playlist("pl", title, creator, (), extension)
        assert is_generated(playlist)

    def test_keeps_a_hand_made_playlist(self):
        assert not is_generated(make_playlist([], title="Songs for the car"))


class TestIsEligible:
    def test_accepts_a_varied_hand_made_playlist(self, varied_playlist):
        assert is_eligible(varied_playlist)

    def test_rejects_short_playlists(self):
        assert not is_eligible(make_playlist([make_track(i) for i in range(5)]))

    def test_rejects_playlists_dominated_by_one_artist(self):
        tracks = [make_track(i, "Same") for i in range(8)]
        tracks += [make_track(i) for i in range(8, 13)]
        assert not is_eligible(make_playlist(tracks))

    def test_max_artist_share_of_empty_is_zero(self):
        assert max_artist_share(()) == 0.0


class TestHeldOutTracks:
    def test_excludes_seed_artists_and_repeats(self):
        seed = make_track(0, "Seed Band")
        tracks = (
            seed,
            make_track(1, "Seed Band"),
            make_track(2),
            make_track(2),
            make_track(3),
        )
        held_out = held_out_tracks(tracks, (seed,))
        assert [t.recording_mbid for t in held_out] == ["rec-2", "rec-3"]

    def test_tracks_without_mbids_stay_distinct_by_track_id(self):
        seed = PlaylistTrack("", "S", "Seed", (), "spotify:track:0")
        others = tuple(
            PlaylistTrack("", f"T{i}", f"A{i}", (), f"spotify:track:{i}")
            for i in range(1, 4)
        )
        assert len(held_out_tracks((seed, *others), (seed,))) == 3

    def test_falls_back_to_artist_name_without_mbids(self):
        seed = PlaylistTrack("rec-0", "S", "Band", ())
        other = PlaylistTrack("rec-1", "T", "band", ())
        assert held_out_tracks((seed, other), (seed,)) == ()


class TestBuildCases:
    def test_builds_one_and_two_seed_cases(self, varied_playlist):
        one, two = build_cases(varied_playlist)
        assert len(one.seeds) == 1
        assert len(two.seeds) == 2
        assert one.seeds[0] == two.seeds[0]
        assert two.seeds[0].artist != two.seeds[1].artist

    def test_is_deterministic(self, varied_playlist):
        assert build_cases(varied_playlist) == build_cases(varied_playlist)

    def test_tags_cases_with_their_group(self, varied_playlist):
        cases = build_cases(varied_playlist, group="indie")
        assert {case.group for case in cases} == {"indie"}
        assert case_from_dict(case_to_dict(cases[0])).group == "indie"

    def test_hashes_the_creator(self, varied_playlist):
        case = build_cases(varied_playlist)[0]
        assert "alice" not in case.creator_hash
        assert len(case.creator_hash) == 12

    def test_single_artist_playlist_yields_no_cases(self):
        playlist = make_playlist([make_track(i, "Solo") for i in range(12)])
        assert build_cases(playlist) == []

    def test_skips_cases_with_too_few_held_out(self):
        tracks = [make_track(i, "A") for i in range(4)]
        tracks += [make_track(i, "B") for i in range(4, 8)]
        assert build_cases(make_playlist(tracks)) == []


class TestSamplingOrder:
    def test_is_independent_of_input_order(self):
        users = [f"user{i}" for i in range(20)]
        assert sampling_order(users) == sampling_order(list(reversed(users)))

    def test_keeps_every_user(self):
        assert sorted(sampling_order(["b", "a", "c"])) == ["a", "b", "c"]


class TestCaseSerialisation:
    def test_round_trips_through_a_dict(self, varied_playlist):
        case = build_cases(varied_playlist)[1]
        assert case_from_dict(case_to_dict(case)) == case


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def limiter(clock):
    return RateLimiter(clock=clock, sleep=clock.sleep)


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def queued(responses):
    queue = list(responses)
    return mock_client(lambda request: queue.pop(0))


class TestRateLimiter:
    async def test_does_not_wait_with_quota_left(self, limiter, clock):
        limiter.record(httpx.Response(200, headers={"X-RateLimit-Remaining": "20"}))
        await limiter.wait()
        assert clock.slept == []

    async def test_waits_for_reset_when_window_is_nearly_spent(self, limiter, clock):
        limiter.record(
            httpx.Response(
                200,
                headers={"X-RateLimit-Remaining": "1", "X-RateLimit-Reset-In": "7"},
            )
        )
        await limiter.wait()
        assert clock.slept == [7.0]

    async def test_waits_after_a_429_without_headers(self, limiter, clock):
        limiter.record(httpx.Response(429))
        await limiter.wait()
        assert clock.slept == [float(catalogue.RATE_LIMIT_FALLBACK_WAIT_SECONDS)]


class TestFetchJson:
    async def test_returns_the_body(self, limiter):
        client = queued([httpx.Response(200, json={"ok": True})])
        assert await fetch_json(client, limiter, "/x", {}) == {"ok": True}

    async def test_retries_after_a_rate_limit(self, limiter):
        client = queued(
            [
                httpx.Response(429, headers={"X-RateLimit-Reset-In": "1"}),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        assert await fetch_json(client, limiter, "/x", {}) == {"ok": True}

    async def test_retries_a_dropped_connection(self, limiter, clock):
        attempts = []

        def handler(request):
            attempts.append(request)
            if len(attempts) == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return httpx.Response(200, json={"ok": True})

        assert await fetch_json(mock_client(handler), limiter, "/x", {}) == {"ok": True}
        assert clock.slept == [backoff_seconds(1)]

    async def test_not_found_is_an_answer_not_a_failure(self, limiter):
        assert await fetch_json(queued([httpx.Response(404)]), limiter, "/x", {}) is None

    async def test_aborts_after_repeated_server_errors(self, limiter):
        client = queued([httpx.Response(503)] * catalogue.MAX_ATTEMPTS)
        with pytest.raises(CatalogueIncomplete, match="HTTP 503"):
            await fetch_json(client, limiter, "/x", {})

    async def test_aborts_immediately_on_a_client_error(self, limiter):
        with pytest.raises(CatalogueIncomplete, match="400"):
            await fetch_json(queued([httpx.Response(400)]), limiter, "/x", {})

    @pytest.mark.parametrize("attempt, expected", [(1, 2.0), (3, 8.0), (10, 60.0)])
    def test_backoff_doubles_up_to_a_cap(self, attempt, expected):
        assert backoff_seconds(attempt) == expected


def playlist_header(mbid, title="Mix", creator="alice", extension=None):
    return {
        "playlist": {
            "identifier": f"https://listenbrainz.org/playlist/{mbid}",
            "title": title,
            "creator": creator,
            "extension": {catalogue.PLAYLIST_EXTENSION: extension or {}},
        }
    }


# A small ListenBrainz: alice follows bob, bob is followed by carol
@pytest.fixture
def fake_listenbrainz():
    graph = {
        "alice": {"followers": [], "following": ["bob"]},
        "bob": {"followers": ["carol", "alice"], "following": []},
        "carol": {"followers": [], "following": ["bob"]},
    }
    playlists = {
        "alice": [
            playlist_header("pl-a1", creator="alice"),
            playlist_header("pl-a2", title="Daily Jams for alice", creator="alice"),
        ],
        "bob": [
            playlist_header(
                "pl-b1",
                creator="bob",
                extension={"additional_metadata": {"algorithm_metadata": {}}},
            )
        ],
        "carol": [playlist_header("pl-c1", creator="carol")],
    }
    full = {
        "pl-a1": [raw_track(f"a{i}", creator=f"Artist {i}", artists=[f"m{i}"]) for i in range(12)],
        "pl-c1": [raw_track("c1", creator="Only")],
    }

    def handler(request):
        parts = request.url.path.strip("/").split("/")
        if parts[1] == "user" and parts[2] not in graph:
            return httpx.Response(404)
        if parts[1] == "user" and parts[3] in ("followers", "following"):
            return httpx.Response(200, json={parts[3]: graph[parts[2]][parts[3]]})
        if parts[1] == "user" and parts[3] == "playlists":
            entries = playlists[parts[2]]
            return httpx.Response(
                200, json={"playlists": entries, "playlist_count": len(entries)}
            )
        if parts[1] == "playlist" and parts[2] in full:
            header = playlist_header(parts[2])["playlist"]
            return httpx.Response(200, json={"playlist": {**header, "track": full[parts[2]]}})
        return httpx.Response(404)

    return mock_client(handler)


class TestDiscoverUsers:
    async def test_walks_the_graph_and_drops_generated_playlists(
        self, fake_listenbrainz, limiter
    ):
        found = await discover_users(
            fake_listenbrainz, limiter, ResponseCache(), roots=("alice",)
        )
        assert found == {"alice": ["pl-a1"], "bob": [], "carol": ["pl-c1"]}

    async def test_stops_at_the_user_limit(self, fake_listenbrainz, limiter):
        found = await discover_users(
            fake_listenbrainz, limiter, ResponseCache(), roots=("alice",), max_users=2
        )
        assert list(found) == ["alice", "bob"]


class TestPickPlaylists:
    async def test_keeps_only_eligible_playlists(self, fake_listenbrainz, limiter):
        candidates = {"alice": ["pl-a1"], "bob": [], "carol": ["pl-c1"]}
        picked, fetched = await pick_playlists(
            fake_listenbrainz, limiter, ResponseCache(), candidates, limit=5
        )
        assert [p.playlist_mbid for p in picked] == ["pl-a1"]
        assert fetched == 2

    async def test_stops_at_the_playlist_limit(self, fake_listenbrainz, limiter):
        candidates = {"alice": ["pl-a1"], "carol": ["pl-c1"]}
        picked, _ = await pick_playlists(
            fake_listenbrainz, limiter, ResponseCache(), candidates, limit=0
        )
        assert picked == []


class TestUnreadableBody:
    async def test_retries_an_empty_success_body(self, limiter):
        client = queued(
            [httpx.Response(200, content=b""), httpx.Response(200, json={"ok": 1})]
        )
        assert await fetch_json(client, limiter, "/x", {}) == {"ok": 1}

    async def test_aborts_when_the_body_never_parses(self, limiter):
        client = queued([httpx.Response(200, content=b"")] * catalogue.MAX_ATTEMPTS)
        with pytest.raises(CatalogueIncomplete, match="invalid JSON"):
            await fetch_json(client, limiter, "/x", {})


class TestResponseCache:
    async def test_second_request_is_served_from_the_cache(self, limiter):
        cache = ResponseCache()
        client = queued([httpx.Response(200, json={"n": 1})])
        first = await fetch_json(client, limiter, "/x", {"a": 1}, cache)
        second = await fetch_json(client, limiter, "/x", {"a": 1}, cache)
        assert first == second == {"n": 1}

    async def test_caches_a_404_as_none(self, limiter):
        cache = ResponseCache()
        await fetch_json(queued([httpx.Response(404)]), limiter, "/gone", {}, cache)
        assert ResponseCache.key("/gone", {}) in cache
        assert cache.get(ResponseCache.key("/gone", {})) is None

    def test_key_ignores_parameter_order(self):
        assert ResponseCache.key("/x", {"a": 1, "b": 2}) == ResponseCache.key(
            "/x", {"b": 2, "a": 1}
        )

    def test_persists_and_reloads(self, tmp_path):
        path = tmp_path / "cache.json"
        cache = ResponseCache(path)
        cache.put("k", {"v": 1})
        cache.flush()
        assert ResponseCache(path).get("k") == {"v": 1}

    def test_flushes_automatically_after_enough_entries(self, tmp_path):
        path = tmp_path / "cache.json"
        cache = ResponseCache(path)
        for index in range(catalogue.CACHE_FLUSH_EVERY):
            cache.put(f"k{index}", {})
        assert path.exists()


class TestUserPath:
    @pytest.mark.parametrize(
        "user, expected",
        [
            ("rob", "/user/rob/playlists"),
            ("Ruud v A", "/user/Ruud%20v%20A/playlists"),
            ("a?b#c%d/e", "/user/a%3Fb%23c%25d%2Fe/playlists"),
        ],
    )
    def test_escapes_every_reserved_character(self, user, expected):
        assert user_path(user, "playlists") == expected

    async def test_request_reaches_the_server_with_the_whole_name(self, limiter):
        seen = []

        def handler(request):
            seen.append(request.url.raw_path.decode())
            return httpx.Response(200, json={"followers": []})

        await fetch_json(mock_client(handler), limiter, user_path("a?b#c", "followers"), {})
        assert seen == ["/1/user/a%3Fb%23c/followers"]


class TestUnreachableUsers:
    async def test_user_whose_playlists_404_is_marked_unreachable(
        self, fake_listenbrainz, limiter
    ):
        found = await discover_users(
            fake_listenbrainz, limiter, ResponseCache(), roots=("ghost",), max_users=1
        )
        assert found == {"ghost": None}

    async def test_unreachable_users_are_skipped_when_picking(
        self, fake_listenbrainz, limiter
    ):
        candidates = {"ghost": None, "alice": ["pl-a1"]}
        picked, _ = await pick_playlists(
            fake_listenbrainz, limiter, ResponseCache(), candidates, limit=5
        )
        assert [p.playlist_mbid for p in picked] == ["pl-a1"]

    def test_payload_counts_unreachable_users(self):
        payload = catalogue.catalogue_payload({"ghost": None, "a": []}, 0, [], [])
        assert payload["counts"]["users_with_unreachable_playlists"] == 1
