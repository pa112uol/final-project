import pytest
from recommendations.types import (
    Track,
    StreamingLinks,
    Release,
    Candidate,
    ScoredCandidate,
    Seed,
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
            "mbid", "title", "artist", "artistMbid", "durationMs",
            "firstReleaseDate", "releases", "streaming",
            "relevanceScore", "noveltyScore", "tags",
        ):
            assert key in d, f"missing key: {key}"

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
        for key in ("appleMusic", "preview", "youtubeVideoId", "spotify"):
            assert key in d["streaming"], f"missing streaming key: {key}"

    def test_streaming_values_match_input(self):
        sl = make_streaming(apple_music="https://music.apple.com/x", youtube_video_id="yt999")
        d = make_track(streaming=sl).to_dict()
        assert d["streaming"]["appleMusic"] == "https://music.apple.com/x"
        assert d["streaming"]["youtubeVideoId"] == "yt999"

    def test_release_objects_serialized_as_dicts(self):
        releases = [Release(mbid="rel1", title="Pablo Honey", date="1993")]
        d = make_track(releases=releases).to_dict()
        assert d["releases"] == [{"mbid": "rel1", "title": "Pablo Honey", "date": "1993"}]

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
        assert d["releases"][0] == {"mbid": "rel1", "title": "Pablo Honey", "date": "1993"}
        assert d["releases"][1] == {"mbid": "rel2", "title": "The Bends", "date": "1995"}

    def test_tags_preserved(self):
        d = make_track(tags=["rock", "alternative", "indie"]).to_dict()
        assert d["tags"] == ["rock", "alternative", "indie"]

    def test_none_optional_fields_preserved(self):
        d = make_track(duration_ms=None, first_release_date=None).to_dict()
        assert d["durationMs"] is None
        assert d["firstReleaseDate"] is None

    def test_none_streaming_urls_preserved(self):
        sl = make_streaming(apple_music=None, preview=None, youtube_video_id=None)
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
