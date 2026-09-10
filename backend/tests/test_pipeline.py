import pytest
from recommendations.pipeline import (
    run_pipeline,
    select_enrichment_targets,
    enrich_selected_tracks,
    enrich_mode,
    build_track_from_candidate,
)
from recommendations.constants import (
    ENRICH_TOP_ARTISTS,
    ENRICH_TRACKS_PER_ARTIST,
    MAX_TRACKS_PER_ARTIST,
    HIGH_NOVELTY_ENRICH_THRESHOLD,
    SELECTION_FOR_VARIETY,
    SELECTION_TOP_MATCH,
)
from recommendations.types import (
    Seed,
    StreamingLinks,
    Candidate,
    spotify_search_url,
)


def make_streaming():
    return StreamingLinks(
        apple_music=None,
        preview=None,
        youtube_video_id=None,
        spotify="https://open.spotify.com/search/test",
    )


def make_resolved(
    mbid, duration_ms=None, album=None, release_mbid=None, release_date=None
):
    return {
        "mbid": mbid,
        "duration_ms": duration_ms,
        "album": album,
        "release_mbid": release_mbid,
        "release_date": release_date,
    }


def make_clients(**overrides):
    class Clients:
        async def fetch_recording_tags(self, mbid):
            return []

        async def fetch_track_tags(self, title, artist, api_key, mbid=None):
            return [
                {"name": "shoegaze", "count": 80},
                {"name": "dreampop", "count": 60},
            ]

        async def fetch_track_tags_only(
            self, title, artist, api_key, mbid=None
        ):
            return []

        async def fetch_tag_artists(self, tag, page, limit, api_key):
            return [
                {"name": "Slowdive", "mbid": "mbid-slowdive"},
                {"name": "Ride", "mbid": "mbid-ride"},
            ]

        async def fetch_top_recordings_for_artist(
            self, mbid, name, limit, api_key
        ):
            tracks = {
                "mbid-slowdive": [
                    {
                        "mbid": "rec-alison",
                        "title": "Alison",
                        "artist_mbid": "mbid-slowdive",
                        "duration_ms": 300000,
                        "listen_count": 50000,
                        "user_count": 20000,
                        "tags": ["shoegaze"],
                    },
                    {
                        "mbid": "rec-when-sun",
                        "title": "When the Sun Hits",
                        "artist_mbid": "mbid-slowdive",
                        "duration_ms": 260000,
                        "listen_count": 40000,
                        "user_count": 15000,
                        "tags": ["shoegaze"],
                    },
                ],
                "mbid-ride": [
                    {
                        "mbid": "rec-vapour-trail",
                        "title": "Vapour Trail",
                        "artist_mbid": "mbid-ride",
                        "duration_ms": 240000,
                        "listen_count": 30000,
                        "user_count": 10000,
                        "tags": ["shoegaze"],
                    },
                ],
            }
            return tracks.get(mbid, [])

        async def resolve_artist_mbid(self, name):
            return ""

        async def fetch_artist_popularity(self, mbids):
            return {}

        async def resolve_recording_mbid(self, mbid, title, artist):
            return make_resolved(mbid)

        async def get_streaming_links(self, artist, title):
            return make_streaming()

    clients = Clients()
    for k, v in overrides.items():
        setattr(clients, k, v)
    return clients


TEST_SEED = Seed(
    mbid="seed-mbid-1", title="souvlaki space station", artist="slowdive"
)


class TestRunPipeline:
    async def test_returns_an_array_of_track_objects(self):
        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, make_clients()
        )
        assert isinstance(tracks, list)
        for t in tracks:
            assert hasattr(t, "mbid")
            assert hasattr(t, "title")
            assert hasattr(t, "artist")
            assert hasattr(t, "streaming")
            assert isinstance(t.relevance_score, float)
            assert isinstance(t.novelty_score, float)

    async def test_every_track_carries_the_reason_mmr_selected_it(self):
        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, make_clients()
        )
        assert tracks
        for t in tracks:
            assert t.selection_reason in (
                SELECTION_TOP_MATCH,
                SELECTION_FOR_VARIETY,
            )

    async def test_returns_empty_when_no_tags_can_be_derived(self):
        clients = make_clients()
        clients.fetch_track_tags = lambda *a, **kw: [].__iter__().__next__
        # Override both tag fetches to return empty

        class EmptyTagClients:
            async def fetch_recording_tags(self, mbid):
                return []

            async def fetch_track_tags(self, title, artist, api_key, mbid=None):
                return []

            async def fetch_track_tags_only(
                self, title, artist, api_key, mbid=None
            ):
                return []

            async def fetch_tag_artists(self, tag, page, limit, api_key):
                return []

            async def fetch_top_recordings_for_artist(
                self, mbid, name, limit, api_key
            ):
                return []

            async def resolve_artist_mbid(self, name):
                return ""

            async def fetch_artist_popularity(self, mbids):
                return {}

            async def resolve_recording_mbid(self, mbid, title, artist):
                return make_resolved(mbid)

            async def get_streaming_links(self, artist, title):
                return make_streaming()

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, EmptyTagClients()
        )
        assert tracks == []

    async def test_excludes_the_seed_track_itself_from_results(self):
        class SeedIncludedClients(make_clients().__class__):
            async def fetch_top_recordings_for_artist(
                self, mbid, name, limit, api_key
            ):
                return [
                    {
                        "mbid": "seed-track-rec",
                        "title": "Souvlaki Space Station",
                        "artist_mbid": "mbid-slowdive",
                        "duration_ms": None,
                        "listen_count": 99999,
                        "user_count": 50000,
                        "tags": ["shoegaze"],
                    },
                    {
                        "mbid": "rec-alison",
                        "title": "Alison",
                        "artist_mbid": "mbid-slowdive",
                        "duration_ms": 300000,
                        "listen_count": 50000,
                        "user_count": 20000,
                        "tags": ["shoegaze"],
                    },
                ]

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, SeedIncludedClients()
        )
        titles = [t.title.lower() for t in tracks]
        assert "souvlaki space station" not in titles

    async def test_calls_get_streaming_links_for_each_returned_track(self):
        calls = []

        async def get_streaming_links(artist, title):
            calls.append((artist, title))
            return make_streaming()

        clients = make_clients()
        clients.get_streaming_links = get_streaming_links
        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, clients
        )
        assert len(calls) == len(tracks)

    async def test_keeps_source_duration_when_already_present(self):
        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, make_clients()
        )
        assert tracks
        assert all(t.duration_ms is not None for t in tracks)

    # Recording resolution is deferred to /api/recording/, so a source with no
    # duration for a track leaves it null rather than resolving it inline
    async def test_duration_stays_null_when_source_has_none(self):
        class NoDurationClients(make_clients().__class__):
            async def fetch_top_recordings_for_artist(
                self, mbid, name, limit, api_key
            ):
                return [
                    {
                        "mbid": "rec-no-duration",
                        "title": "Alison",
                        "artist_mbid": "mbid-slowdive",
                        "duration_ms": None,
                        "listen_count": 50000,
                        "user_count": 20000,
                        "tags": ["shoegaze"],
                    },
                ]

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, NoDurationClients()
        )
        assert tracks
        assert all(t.duration_ms is None for t in tracks)

    async def test_never_resolves_the_recording_and_releases_stay_empty(self):
        async def boom(mbid, title, artist):
            raise AssertionError("resolve_recording_mbid should not be called")

        clients = make_clients(resolve_recording_mbid=boom)
        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, clients
        )
        assert tracks
        assert all(t.mbid for t in tracks)
        assert all(t.first_release_date is None for t in tracks)
        assert all(t.releases == [] for t in tracks)

    async def test_mood_ranks_matching_candidate_above_relevance_equal_peer(
        self,
    ):
        # Both candidates share an artist (equal tag_weight_sum) and carry one
        # seed tag plus one non-seed tag, so their relevance is identical and
        # the mood tag is the only thing separating them.
        class MoodClients(make_clients().__class__):
            async def fetch_top_recordings_for_artist(
                self, mbid, name, limit, api_key
            ):
                return [
                    {
                        "mbid": "rec-happy",
                        "title": "Happy Track",
                        "artist_mbid": "mbid-ride",
                        "duration_ms": None,
                        "listen_count": 100,
                        "user_count": 50,
                        "tags": ["shoegaze", "happy"],
                    },
                    {
                        "mbid": "rec-neutral",
                        "title": "Neutral Track",
                        "artist_mbid": "mbid-ride",
                        "duration_ms": None,
                        "listen_count": 100,
                        "user_count": 50,
                        "tags": ["shoegaze", "noise pop"],
                    },
                ]

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", "happy", 0, MoodClients()
        )
        order = [t.mbid for t in tracks]
        assert order.index("rec-happy") < order.index("rec-neutral")

    async def test_mood_fires_on_lf_enrichment_tags_not_just_lb_recording_tags(
        self,
    ):
        # LB recording tags are pure genre labels here; the mood word arrives
        # only via Last.fm enrichment. Both candidates gain exactly one tag so
        # the cosine length penalty applies equally and relevance stays tied.
        class MoodEnrichClients(make_clients().__class__):
            async def fetch_top_recordings_for_artist(
                self, mbid, name, limit, api_key
            ):
                return [
                    {
                        "mbid": "rec-chill",
                        "title": "Chill Track",
                        "artist_mbid": "mbid-ride",
                        "duration_ms": None,
                        "listen_count": 100,
                        "user_count": 50,
                        "tags": ["shoegaze"],
                    },
                    {
                        "mbid": "rec-other",
                        "title": "Other Track",
                        "artist_mbid": "mbid-ride",
                        "duration_ms": None,
                        "listen_count": 100,
                        "user_count": 50,
                        "tags": ["shoegaze"],
                    },
                ]

            async def fetch_track_tags_only(
                self, title, artist, api_key, mbid=None
            ):
                if title == "Chill Track":
                    return [{"name": "chillout", "count": 80}]
                return [{"name": "noise pop", "count": 80}]

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", "chill", 0, MoodEnrichClients()
        )
        order = [t.mbid for t in tracks]
        assert order.index("rec-chill") < order.index("rec-other")

    async def test_unknown_mood_leaves_results_identical_to_no_mood(self):
        clients = make_clients()
        baseline = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, clients
        )
        unknown = await run_pipeline(
            [TEST_SEED], "fake-api-key", "not-a-mood", 0, clients
        )
        assert [t.mbid for t in unknown] == [t.mbid for t in baseline]

    async def test_respects_novelty_one_by_using_artist_popularity_client(self):
        calls = []

        async def fetch_artist_popularity(mbids):
            calls.append(mbids)
            return {}

        clients = make_clients()
        clients.fetch_artist_popularity = fetch_artist_popularity
        await run_pipeline([TEST_SEED], "fake-api-key", None, 1, clients)
        assert len(calls) > 0

    async def test_still_returns_tracks_when_artist_popularity_fails(self):
        async def fetch_artist_popularity(mbids):
            raise RuntimeError("ListenBrainz down")

        clients = make_clients()
        clients.fetch_artist_popularity = fetch_artist_popularity
        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 1, clients
        )
        assert tracks
        assert all(0 <= t.novelty_score <= 1 for t in tracks)

    async def test_excludes_all_tracks_by_seed_artist_by_default(self):
        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, make_clients()
        )
        artists = [t.artist.lower() for t in tracks]
        assert "slowdive" not in artists

    async def test_allows_seed_artist_tracks_when_exclude_seed_artists_is_false(
        self,
    ):
        tracks = await run_pipeline(
            [TEST_SEED],
            "fake-api-key",
            None,
            0,
            make_clients(),
            exclude_seed_artists=False,
        )
        artists = [t.artist.lower() for t in tracks]
        assert "slowdive" in artists

    async def test_excludes_tracks_with_no_seed_tag_match_when_pool_has_enough(
        self,
    ):
        # 5 shoegaze artists x 2 tracks each = 10 matching tracks after artist cap
        # (= RECOMMENDATION_LIMIT), plus 1 wrong-genre artist whose tracks should be filtered out
        matching_artists = [
            {"name": f"ShoegazeBand{i}", "mbid": f"mbid-sg-{i}"}
            for i in range(5)
        ]

        class FilterClients(make_clients().__class__):
            async def fetch_tag_artists(self, tag, page, limit, api_key):
                return matching_artists + [
                    {"name": "WrongGenreBand", "mbid": "mbid-wrong"}
                ]

            async def fetch_top_recordings_for_artist(
                self, mbid, name, limit, api_key
            ):
                if mbid == "mbid-wrong":
                    return [
                        {
                            "mbid": f"wrong-{i}",
                            "title": f"Wrong Genre Track {i}",
                            "artist_mbid": "mbid-wrong",
                            "duration_ms": None,
                            "listen_count": 500,
                            "user_count": 200,
                            "tags": ["jazz", "classical"],
                        }
                        for i in range(5)
                    ]
                return [
                    {
                        "mbid": f"{mbid}-a",
                        "title": f"Sg Track A by {mbid}",
                        "artist_mbid": mbid,
                        "duration_ms": None,
                        "listen_count": 1000,
                        "user_count": 500,
                        "tags": ["shoegaze"],
                    },
                    {
                        "mbid": f"{mbid}-b",
                        "title": f"Sg Track B by {mbid}",
                        "artist_mbid": mbid,
                        "duration_ms": None,
                        "listen_count": 800,
                        "user_count": 400,
                        "tags": ["shoegaze"],
                    },
                ]

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, FilterClients()
        )
        titles = [t.title for t in tracks]
        assert not any(title.startswith("Wrong Genre") for title in titles)
        assert any(title.startswith("Sg ") for title in titles)

    async def test_keeps_zero_tag_score_tracks_when_filtering_would_leave_fewer_than_limit(
        self,
    ):
        # 3 distinct artists with non-matching tags - pool stays below RECOMMENDATION_LIMIT (10)
        class SmallPoolClients(make_clients().__class__):
            async def fetch_tag_artists(self, tag, page, limit, api_key):
                return [
                    {"name": "Band A", "mbid": "mbid-band-a"},
                    {"name": "Band B", "mbid": "mbid-band-b"},
                    {"name": "Band C", "mbid": "mbid-band-c"},
                ]

            async def fetch_top_recordings_for_artist(
                self, mbid, name, limit, api_key
            ):
                return [
                    {
                        "mbid": f"{mbid}-track",
                        "title": f"Track by {mbid}",
                        "artist_mbid": mbid,
                        "duration_ms": None,
                        "listen_count": 500,
                        "user_count": 200,
                        "tags": ["jazz"],
                    }
                ]

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, SmallPoolClients()
        )
        # Pool too small to filter all 3 tracks survive
        assert len(tracks) == 3


def make_candidate(artist, title, tag_weight_sum=100, listen_count=0):
    return Candidate(
        title=title,
        artist=artist,
        artist_mbid=f"am-{artist}",
        mbid=f"m-{artist}-{title}",
        duration_ms=None,
        tag_weight_sum=tag_weight_sum,
        track_tag_score=0,
        listen_count=listen_count,
        user_count=0,
        artist_listen_count=0,
        tags=[],
    )


@pytest.fixture
def budget_on(monkeypatch):
    monkeypatch.setenv("RECS_ENRICH_MODE", "budget")


@pytest.fixture
def budget_off(monkeypatch):
    monkeypatch.setenv("RECS_ENRICH_MODE", "all")


class TestSelectEnrichmentTargets:
    def test_returns_every_candidate_in_all_mode(self, budget_off):
        candidates = [make_candidate("A", f"t{i}") for i in range(50)]
        assert len(select_enrichment_targets(candidates)) == 50

    def test_keeps_only_the_most_listened_tracks_per_artist(self, budget_on):
        candidates = [
            make_candidate("A", f"t{i}", listen_count=i) for i in range(6)
        ]
        titles = [c.title for c in select_enrichment_targets(candidates)]
        assert len(titles) == ENRICH_TRACKS_PER_ARTIST
        # Highest listen counts are t5, t4, t3
        assert titles == ["t5", "t4", "t3"]

    def test_limits_how_many_artists_are_enriched(self, budget_on):
        candidates = [
            make_candidate(f"A{i}", "t", tag_weight_sum=100 - i)
            for i in range(ENRICH_TOP_ARTISTS + 10)
        ]
        targets = select_enrichment_targets(candidates)
        assert len({c.artist for c in targets}) == ENRICH_TOP_ARTISTS

    def test_prefers_artists_with_the_highest_tag_weight_sum(self, budget_on):
        candidates = [make_candidate("Weak", "t", tag_weight_sum=1)] + [
            make_candidate(f"Strong{i}", "t", tag_weight_sum=100)
            for i in range(ENRICH_TOP_ARTISTS)
        ]
        artists = {c.artist for c in select_enrichment_targets(candidates)}
        assert "Weak" not in artists

    def test_enriches_more_tracks_than_the_artist_cap_can_use(self):
        # The cap picks MAX_TRACKS_PER_ARTIST per artist, so enriching exactly
        # that many would leave the cap no informed choice
        assert ENRICH_TRACKS_PER_ARTIST > MAX_TRACKS_PER_ARTIST

    def test_returns_empty_for_no_candidates(self, budget_on):
        assert select_enrichment_targets([]) == []

    def test_final_mode_defers_all_pre_selection_enrichment(self, monkeypatch):
        monkeypatch.setenv("RECS_ENRICH_MODE", "final")
        candidates = [make_candidate("A", f"t{i}") for i in range(20)]
        assert select_enrichment_targets(candidates) == []

    def test_hybrid_mode_still_enriches_a_capped_subset(self, monkeypatch):
        monkeypatch.setenv("RECS_ENRICH_MODE", "hybrid")
        candidates = [
            make_candidate(f"A{i}", "t", tag_weight_sum=100 - i)
            for i in range(ENRICH_TOP_ARTISTS + 10)
        ]
        targets = select_enrichment_targets(candidates)
        assert 0 < len(targets) <= ENRICH_TOP_ARTISTS * ENRICH_TRACKS_PER_ARTIST

    def test_unknown_mode_falls_back_to_the_default(self, monkeypatch):
        # Default is auto, which without a novelty resolves to hybrid, so an
        # unusable value degrades to a capped budget rather than crashing
        monkeypatch.setenv("RECS_ENRICH_MODE", "nonsense")
        candidates = [make_candidate("A", f"t{i}") for i in range(5)]
        assert (
            len(select_enrichment_targets(candidates))
            == ENRICH_TRACKS_PER_ARTIST
        )


class TestEnrichSelectedTracks:
    def _clients(self, calls):
        class C:
            async def fetch_track_tags_only(
                self, title, artist, api_key, mbid=None
            ):
                calls.append(title)
                return [{"name": "shoegaze", "count": 100}]

        return C()

    async def test_skips_tracks_the_pre_selection_pass_already_fetched(
        self, monkeypatch
    ):
        monkeypatch.setenv("RECS_ENRICH_MODE", "hybrid")
        calls = []
        already = make_candidate("A", "done")
        already.lf_enriched = True
        fresh = make_candidate("B", "todo")
        await enrich_selected_tracks(
            [already, fresh], self._clients(calls), "key", {"shoegaze": 10}
        )
        assert calls == ["todo"]

    async def test_does_nothing_in_all_mode(self, monkeypatch):
        monkeypatch.setenv("RECS_ENRICH_MODE", "all")
        calls = []
        await enrich_selected_tracks(
            [make_candidate("A", "t")], self._clients(calls), "key", {}
        )
        assert calls == []

    async def test_fetches_every_selected_track_in_final_mode(
        self, monkeypatch
    ):
        monkeypatch.setenv("RECS_ENRICH_MODE", "final")
        calls = []
        selected = [make_candidate("A", "t1"), make_candidate("B", "t2")]
        await enrich_selected_tracks(
            selected, self._clients(calls), "key", {"shoegaze": 10}
        )
        assert sorted(calls) == ["t1", "t2"]
        assert all(c.lf_enriched for c in selected)


class TestAutoEnrichMode:
    @pytest.fixture(autouse=True)
    def auto_mode(self, monkeypatch):
        monkeypatch.delenv("RECS_ENRICH_MODE", raising=False)

    def test_low_novelty_keeps_the_richer_hybrid_mode(self):
        assert enrich_mode(0.0) == "hybrid"

    def test_high_novelty_switches_to_final(self):
        assert enrich_mode(1.0) == "final"

    def test_switches_exactly_at_the_threshold(self):
        assert enrich_mode(HIGH_NOVELTY_ENRICH_THRESHOLD) == "final"
        assert enrich_mode(HIGH_NOVELTY_ENRICH_THRESHOLD - 0.01) == "hybrid"

    def test_unknown_novelty_prefers_the_richer_mode(self):
        assert enrich_mode(None) == "hybrid"

    def test_explicit_env_mode_overrides_novelty(self, monkeypatch):
        monkeypatch.setenv("RECS_ENRICH_MODE", "all")
        assert enrich_mode(1.0) == "all"
        assert enrich_mode(0.0) == "all"


class TestBuildTrackFromCandidate:
    def _candidate(self, **overrides):
        candidate = make_candidate("Slowdive", "Alison")
        candidate.duration_ms = 300000
        for k, v in overrides.items():
            setattr(candidate, k, v)
        return candidate

    async def test_keeps_the_candidates_own_mbid_and_duration(self):
        candidate = self._candidate()
        track = await build_track_from_candidate(candidate, make_clients())
        assert track.mbid == candidate.mbid
        assert track.duration_ms == candidate.duration_ms

    async def test_leaves_release_info_unresolved(self):
        candidate = self._candidate()
        track = await build_track_from_candidate(candidate, make_clients())
        assert track.releases == []
        assert track.first_release_date is None

    # Recording resolution belongs to /api/recording/ now, not the pipeline
    async def test_never_calls_resolve_recording_mbid(self):
        async def boom(mbid, title, artist):
            raise AssertionError("resolve_recording_mbid should not be called")

        clients = make_clients(resolve_recording_mbid=boom)
        candidate = self._candidate()
        # Raises only if build_track_from_candidate still calls it
        await build_track_from_candidate(candidate, clients)

    async def test_still_fetches_streaming_links(self):
        calls = []

        async def get_streaming_links(artist, title):
            calls.append((artist, title))
            return make_streaming()

        clients = make_clients(get_streaming_links=get_streaming_links)
        candidate = self._candidate()
        await build_track_from_candidate(candidate, clients)
        assert calls == [(candidate.artist, candidate.title)]

    async def test_streaming_lookup_is_skipped_when_the_flag_is_off(
        self, monkeypatch
    ):
        monkeypatch.setenv("RECS_STREAMING_LINKS", "0")
        calls = []

        async def get_streaming_links(artist, title):
            calls.append((artist, title))
            return make_streaming()

        clients = make_clients(get_streaming_links=get_streaming_links)
        track = await build_track_from_candidate(self._candidate(), clients)
        assert calls == []
        assert track.streaming.apple_music is None
        assert track.streaming.youtube_video_id is None

    async def test_the_spotify_search_link_survives_a_skipped_lookup(
        self, monkeypatch
    ):
        monkeypatch.setenv("RECS_STREAMING_LINKS", "0")
        candidate = self._candidate()
        track = await build_track_from_candidate(candidate, make_clients())
        assert track.streaming.spotify == spotify_search_url(
            candidate.artist, candidate.title
        )
        assert track.streaming.lookup_failed is False

    async def test_preserves_tags_used_for_ranking_after_later_enrichment(self):
        candidate = self._candidate(
            tags=["shoegaze", "mellow"],
            ranking_tags=["shoegaze"],
        )
        track = await build_track_from_candidate(candidate, make_clients())

        assert track.tags == ["shoegaze", "mellow"]
        assert track.ranking_tags == ["shoegaze"]
        assert track.to_dict()["rankingTags"] == ["shoegaze"]

    @pytest.mark.parametrize("value", ["1", "true", "yes"])
    async def test_truthy_flag_values_keep_the_lookup(
        self, monkeypatch, value
    ):
        monkeypatch.setenv("RECS_STREAMING_LINKS", value)
        calls = []

        async def get_streaming_links(artist, title):
            calls.append((artist, title))
            return make_streaming()

        clients = make_clients(get_streaming_links=get_streaming_links)
        await build_track_from_candidate(self._candidate(), clients)
        assert len(calls) == 1
