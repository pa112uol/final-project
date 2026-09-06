import pytest
from recommendations.constants import (
    SELECTION_FOR_VARIETY,
    SELECTION_TOP_MATCH,
)
from recommendations.types import (
    Track,
    StreamingLinks,
    Release,
    Candidate,
    ScoredCandidate,
    Seed,
    releases_from_resolved,
    resolved_to_dict,
    search_only_streaming_links,
    spotify_search_url,
)


def make_streaming(**kwargs):
    defaults = {
        "apple_music": "https://music.apple.com/track/1",
        "preview": "https://preview.example.com/audio.m4a",
        "youtube_video_id": "abc123",
        "spotify": "https://open.spotify.com/search/test",
    }
    defaults.update(kwargs)
    return StreamingLinks(**defaults)


def make_resolved(**kwargs):
    defaults = {
        "mbid": "resolved-mbid-1",
        "duration_ms": 238000,
        "album": "The Bends",
        "release_mbid": "release-mbid-1",
        "release_date": "1995-03-13",
    }
    defaults.update(kwargs)
    return defaults


def make_track(**kwargs):
    defaults = {
        "mbid": "track-mbid-1",
        "title": "Creep",
        "artist": "Radiohead",
        "artist_mbid": "artist-mbid-1",
        "duration_ms": 238000,
        "first_release_date": "1992-09-21",
        "releases": [],
        "streaming": make_streaming(),
        "relevance_score": 0.8,
        "novelty_score": 0.3,
        "tags": ["alternative", "rock"],
    }
    defaults.update(kwargs)
    return Track(**defaults)


class TestTrackToDict:
    def test_contains_all_required_top_level_keys(self):
        d = make_track().to_dict()
        for key in (
            "mbid",
            "title",
            "artist",
            "artistMbid",
            "durationMs",
            "firstReleaseDate",
            "releases",
            "streaming",
            "relevanceScore",
            "noveltyScore",
            "tags",
            "selectionReason",
        ):
            assert key in d, f"missing key: {key}"

    def test_selection_reason_serialized_and_defaults_to_top_match(self):
        assert make_track().to_dict()["selectionReason"] == SELECTION_TOP_MATCH
        d = make_track(selection_reason=SELECTION_FOR_VARIETY).to_dict()
        assert d["selectionReason"] == SELECTION_FOR_VARIETY

    def test_snake_case_fields_mapped_to_camel_case(self):
        t = make_track(
            artist_mbid="art1",
            duration_ms=180000,
            first_release_date="2020-01-01",
            relevance_score=0.9,
            novelty_score=0.1,
        )
        d = t.to_dict()
        assert d["artistMbid"] == "art1"
        assert d["durationMs"] == 180000
        assert d["firstReleaseDate"] == "2020-01-01"
        assert d["relevanceScore"] == 0.9
        assert d["noveltyScore"] == 0.1

    def test_streaming_dict_has_camel_case_keys(self):
        d = make_track().to_dict()
        for key in (
            "appleMusic",
            "preview",
            "youtubeVideoId",
            "spotify",
            "artwork",
        ):
            assert key in d["streaming"], f"missing streaming key: {key}"

    def test_streaming_values_match_input(self):
        sl = make_streaming(
            apple_music="https://music.apple.com/x", youtube_video_id="yt999"
        )
        d = make_track(streaming=sl).to_dict()
        assert d["streaming"]["appleMusic"] == "https://music.apple.com/x"
        assert d["streaming"]["youtubeVideoId"] == "yt999"

    def test_release_objects_serialized_as_dicts(self):
        releases = [Release(mbid="rel1", title="Pablo Honey", date="1993")]
        d = make_track(releases=releases).to_dict()
        assert d["releases"] == [
            {"mbid": "rel1", "title": "Pablo Honey", "date": "1993"}
        ]

    def test_release_dicts_passed_through_unchanged(self):
        releases = [{"mbid": "rel1", "title": "Pablo Honey", "date": "1993"}]
        d = make_track(releases=releases).to_dict()
        assert d["releases"] == releases

    def test_mixed_releases_list_handled(self):
        releases = [
            Release(mbid="rel1", title="Pablo Honey", date="1993"),
            {"mbid": "rel2", "title": "The Bends", "date": "1995"},
        ]
        d = make_track(releases=releases).to_dict()
        assert len(d["releases"]) == 2
        assert d["releases"][0] == {
            "mbid": "rel1",
            "title": "Pablo Honey",
            "date": "1993",
        }
        assert d["releases"][1] == {
            "mbid": "rel2",
            "title": "The Bends",
            "date": "1995",
        }

    def test_tags_preserved(self):
        d = make_track(tags=["rock", "alternative", "indie"]).to_dict()
        assert d["tags"] == ["rock", "alternative", "indie"]

    def test_none_optional_fields_preserved(self):
        d = make_track(duration_ms=None, first_release_date=None).to_dict()
        assert d["durationMs"] is None
        assert d["firstReleaseDate"] is None

    def test_none_streaming_urls_preserved(self):
        sl = make_streaming(
            apple_music=None, preview=None, youtube_video_id=None
        )
        d = make_track(streaming=sl).to_dict()
        assert d["streaming"]["appleMusic"] is None
        assert d["streaming"]["preview"] is None
        assert d["streaming"]["youtubeVideoId"] is None

    def test_empty_releases_list(self):
        d = make_track(releases=[]).to_dict()
        assert d["releases"] == []


class TestDataclassInstantiation:
    def test_seed_stores_fields(self):
        s = Seed(mbid="m1", title="Track", artist="Band")
        assert s.mbid == "m1"
        assert s.title == "Track"
        assert s.artist == "Band"

    def test_release_date_defaults_to_none(self):
        r = Release(mbid="r1", title="Album")
        assert r.date is None

    def test_scored_candidate_inherits_candidate_fields(self):
        sc = ScoredCandidate(
            title="Song",
            artist="Artist",
            artist_mbid="art1",
            mbid="track1",
            duration_ms=None,
            tag_weight_sum=50.0,
            track_tag_score=0.5,
            listen_count=1000,
            user_count=200,
            artist_listen_count=5000,
            tags=["rock"],
        )
        assert sc.title == "Song"
        assert sc.final_score == 0.0
        assert sc.relevance_score == 0.0
        assert sc.novelty_score == 0.0


class TestReleasesFromResolved:
    def test_returns_one_release_when_album_present(self):
        releases = releases_from_resolved(make_resolved())
        assert len(releases) == 1
        r = releases[0]
        assert r.mbid == "release-mbid-1"
        assert r.title == "The Bends"
        assert r.date == "1995-03-13"

    def test_returns_empty_list_when_album_missing(self):
        assert releases_from_resolved(make_resolved(album=None)) == []

    def test_returns_empty_list_when_album_is_empty_string(self):
        assert releases_from_resolved(make_resolved(album="")) == []

    def test_tolerates_null_release_mbid(self):
        releases = releases_from_resolved(make_resolved(release_mbid=None))
        assert releases[0].mbid is None
        assert releases[0].title == "The Bends"


class TestResolvedToDict:
    def test_camel_cases_the_expected_keys(self):
        d = resolved_to_dict(make_resolved())
        assert set(d.keys()) == {
            "mbid",
            "durationMs",
            "firstReleaseDate",
            "releases",
        }

    def test_maps_fields_through(self):
        d = resolved_to_dict(make_resolved())
        assert d["mbid"] == "resolved-mbid-1"
        assert d["durationMs"] == 238000
        assert d["firstReleaseDate"] == "1995-03-13"
        assert d["releases"] == [
            {
                "mbid": "release-mbid-1",
                "title": "The Bends",
                "date": "1995-03-13",
            }
        ]

    def test_preserves_nulls_when_nothing_resolved(self):
        resolved = {
            "mbid": "echoed-mbid",
            "duration_ms": None,
            "album": None,
            "release_mbid": None,
            "release_date": None,
        }
        d = resolved_to_dict(resolved)
        assert d["mbid"] == "echoed-mbid"
        assert d["durationMs"] is None
        assert d["firstReleaseDate"] is None
        assert d["releases"] == []


class TestSpotifySearchUrl:
    def test_builds_a_search_url_from_artist_and_title(self):
        assert (
            spotify_search_url("Slowdive", "Alison")
            == "https://open.spotify.com/search/Slowdive%20Alison"
        )

    @pytest.mark.parametrize(
        "artist,title",
        [
            ("Sigur Rós", "Hoppípolla"),
            ("AC/DC", "Back in Black"),
            ("Godspeed You! Black Emperor", "Storm"),
        ],
    )
    def test_escapes_characters_that_would_break_the_path(self, artist, title):
        url = spotify_search_url(artist, title)
        assert " " not in url
        assert url.startswith("https://open.spotify.com/search/")

    def test_handles_empty_fields(self):
        expected = "https://open.spotify.com/search/%20"
        assert spotify_search_url("", "") == expected


class TestSearchOnlyStreamingLinks:
    def test_leaves_every_looked_up_field_unset(self):
        links = search_only_streaming_links("Slowdive", "Alison")
        assert links.apple_music is None
        assert links.preview is None
        assert links.youtube_video_id is None
        assert links.artwork is None

    def test_still_carries_a_spotify_search_link(self):
        links = search_only_streaming_links("Slowdive", "Alison")
        assert links.spotify == spotify_search_url("Slowdive", "Alison")

    # No lookup was attempted, so nothing failed
    def test_does_not_report_a_failed_lookup(self):
        assert search_only_streaming_links("A", "B").lookup_failed is False

    def test_serialises_through_a_track_without_error(self):
        track = make_track(streaming=search_only_streaming_links("A", "B"))
        payload = track.to_dict()
        assert payload["streaming"]["appleMusic"] is None
        assert payload["streaming"]["spotify"].endswith("A%20B")
