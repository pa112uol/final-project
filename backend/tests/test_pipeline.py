import pytest
from recommendations.pipeline import run_pipeline
from recommendations.types import Seed, StreamingLinks


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

    async def test_falls_back_to_resolved_duration_when_source_has_none(self):
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

            async def resolve_recording_mbid(self, mbid, title, artist):
                return make_resolved(mbid, duration_ms=232000)

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, NoDurationClients()
        )
        assert tracks
        assert all(t.duration_ms == 232000 for t in tracks)

    async def test_populates_album_and_release_date_from_resolved_recording(
        self,
    ):
        class AlbumClients(make_clients().__class__):
            async def resolve_recording_mbid(self, mbid, title, artist):
                return make_resolved(
                    mbid,
                    album="Souvlaki",
                    release_mbid="release-souvlaki",
                    release_date="1993-05-17",
                )

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, AlbumClients()
        )
        assert tracks
        for t in tracks:
            assert t.first_release_date == "1993-05-17"
            assert len(t.releases) == 1
            assert t.releases[0].mbid == "release-souvlaki"
            assert t.releases[0].title == "Souvlaki"
            assert t.releases[0].date == "1993-05-17"

    async def test_leaves_releases_empty_when_resolved_recording_has_no_album(
        self,
    ):
        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", None, 0, make_clients()
        )
        assert tracks
        assert all(t.first_release_date is None for t in tracks)
        assert all(t.releases == [] for t in tracks)

    async def test_applies_mood_boost_happy_candidates_outrank_equal_non_happy(
        self,
    ):
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
                        "tags": ["happy"],
                    },
                    {
                        "mbid": "rec-neutral",
                        "title": "Neutral Track",
                        "artist_mbid": "mbid-ride",
                        "duration_ms": None,
                        "listen_count": 100,
                        "user_count": 50,
                        "tags": ["shoegaze"],
                    },
                ]

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", "happy", 0, MoodClients()
        )
        happy_idx = next(
            (i for i, t in enumerate(tracks) if t.mbid == "rec-happy"), -1
        )
        neutral_idx = next(
            (i for i, t in enumerate(tracks) if t.mbid == "rec-neutral"), -1
        )
        if happy_idx != -1 and neutral_idx != -1:
            assert happy_idx < neutral_idx

    async def test_mood_boost_fires_via_lf_tags_when_lb_recording_tags_contain_no_mood_words(
        self,
    ):
        # This is the scenario where LB tags are pure genre labels; mood words come
        # only from LF enrichment.
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
                    return [{"name": "chill", "count": 80}]
                return []

        tracks = await run_pipeline(
            [TEST_SEED], "fake-api-key", "chill", 0, MoodEnrichClients()
        )
        chill_idx = next(
            (i for i, t in enumerate(tracks) if t.mbid == "rec-chill"), -1
        )
        other_idx = next(
            (i for i, t in enumerate(tracks) if t.mbid == "rec-other"), -1
        )
        assert chill_idx >= 0
        assert other_idx >= 0
        assert chill_idx < other_idx

    async def test_respects_novelty_one_by_using_artist_popularity_client(self):
        calls = []

        async def fetch_artist_popularity(mbids):
            calls.append(mbids)
            return {}

        clients = make_clients()
        clients.fetch_artist_popularity = fetch_artist_popularity
        await run_pipeline([TEST_SEED], "fake-api-key", None, 1, clients)
        assert len(calls) > 0

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
