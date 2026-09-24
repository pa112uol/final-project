import hashlib
import json

import httpx
import pytest

from evaluation import mpd_catalogue as mpd
from evaluation.mpd_catalogue import (
    SliceVerificationError,
    build_catalogue,
    download_slice,
    file_md5,
    parse_md5sums,
    parse_mpd_playlist,
    parse_mpd_track,
    sample_eligible,
    verify_slice,
)
from evaluation.playlist_catalogue import load_cases


def raw_track(pos, artist=None, uri=None):
    return {
        "pos": pos,
        "track_name": f"Song {pos}",
        "artist_name": artist or f"Artist {pos}",
        "track_uri": uri or f"spotify:track:{pos}",
    }


def raw_playlist(pid, tracks):
    return {"pid": pid, "name": f"Playlist {pid}", "tracks": tracks}


def varied(pid, size=12):
    return raw_playlist(pid, [raw_track(i) for i in range(size)])


@pytest.fixture
def slice_file(tmp_path):
    path = tmp_path / "mpd.slice.0-999.json"
    playlists = [varied(pid) for pid in range(5)]
    playlists.append(raw_playlist(5, [raw_track(i, "Solo") for i in range(12)]))
    path.write_text(json.dumps({"info": {}, "playlists": playlists}), encoding="utf-8")
    return path


class TestParseMd5sums:
    def test_maps_file_names_to_hashes(self):
        text = "abc123  data/mpd.slice.0-999.json\ndef456  data/mpd.slice.1000-1999.json\n"
        assert parse_md5sums(text) == {
            "mpd.slice.0-999.json": "abc123",
            "mpd.slice.1000-1999.json": "def456",
        }

    def test_ignores_malformed_lines(self):
        assert parse_md5sums("\njunk\n") == {}


class TestVerification:
    def test_accepts_a_matching_file(self, tmp_path):
        path = tmp_path / "f.json"
        path.write_bytes(b"data")
        verify_slice(path, hashlib.md5(b"data").hexdigest())

    def test_rejects_an_altered_file(self, tmp_path):
        path = tmp_path / "f.json"
        path.write_bytes(b"altered")
        with pytest.raises(SliceVerificationError):
            verify_slice(path, hashlib.md5(b"data").hexdigest())

    def test_file_md5_matches_hashlib(self, tmp_path):
        path = tmp_path / "f.json"
        path.write_bytes(b"x" * 3_000_000)
        assert file_md5(path) == hashlib.md5(b"x" * 3_000_000).hexdigest()


class TestDownloadSlice:
    def _client(self, body):
        return httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        )

    def test_keeps_a_verified_download(self, tmp_path):
        body = b'{"playlists": []}'
        path = download_slice(
            self._client(body), "s.json", tmp_path, hashlib.md5(body).hexdigest()
        )
        assert path.read_bytes() == body

    def test_discards_a_download_that_fails_verification(self, tmp_path):
        with pytest.raises(SliceVerificationError):
            download_slice(self._client(b"tampered"), "s.json", tmp_path, "0" * 32)
        assert list(tmp_path.iterdir()) == []

    def test_reuses_an_existing_verified_file(self, tmp_path):
        (tmp_path / "s.json").write_bytes(b"cached")

        def refuse(request):
            raise AssertionError("a verified file must not be downloaded again")

        client = httpx.Client(transport=httpx.MockTransport(refuse))
        download_slice(client, "s.json", tmp_path, hashlib.md5(b"cached").hexdigest())


class TestParseMpd:
    def test_track_uses_the_spotify_uri_as_identity(self):
        track = parse_mpd_track(raw_track(3))
        assert track.recording_mbid == ""
        assert track.identity == "spotify:track:3"

    @pytest.mark.parametrize("missing", ["track_name", "artist_name", "track_uri"])
    def test_track_without_required_fields_is_dropped(self, missing):
        raw = raw_track(1)
        raw[missing] = ""
        assert parse_mpd_track(raw) is None

    def test_playlist_orders_tracks_by_position(self):
        playlist = parse_mpd_playlist(
            raw_playlist(7, [raw_track(2), raw_track(0), raw_track(1)])
        )
        assert [t.title for t in playlist.tracks] == ["Song 0", "Song 1", "Song 2"]
        assert playlist.playlist_mbid == "mpd7"


class TestSampleEligible:
    def test_drops_ineligible_and_is_deterministic(self, slice_file):
        playlists = mpd.load_slice(slice_file)
        first = sample_eligible(playlists, 10)
        assert len(first) == 5
        assert "mpd5" not in {p.playlist_mbid for p in first}
        assert first == sample_eligible(list(reversed(playlists)), 10)

    def test_respects_the_limit(self, slice_file):
        assert len(sample_eligible(mpd.load_slice(slice_file), 2)) == 2


class TestBuildCatalogue:
    def test_builds_distinct_one_and_two_seed_cases(self, slice_file, tmp_path):
        payload = build_catalogue([slice_file], 10)
        assert payload["counts"]["loaded_playlists"] == 6
        assert payload["counts"]["sampled_playlists"] == 5
        ids = [case["case_id"] for case in payload["cases"]]
        assert len(ids) == len(set(ids)) == 10

    def test_cases_load_back_for_the_evaluation(self, slice_file, tmp_path):
        path = tmp_path / "catalogue.json"
        path.write_text(json.dumps(build_catalogue([slice_file], 10)), encoding="utf-8")
        cases = load_cases(path)
        assert cases[0].seeds[0].track_id.startswith("spotify:track:")
        assert cases[0].seeds[0].recording_mbid == ""


def titled(pid, title, size=12):
    return parse_mpd_playlist({**varied(pid, size), "name": title})


class TestGenreOf:
    @pytest.mark.parametrize(
        "title, genre",
        [
            ("Classic Rock", "classic_rock"),
            ("classic rock 70s", "classic_rock"),
            ("indie vibes", "indie"),
            ("Pop", "pop"),
            ("pop hits", "pop"),
            ("CHILL EDM", "electronic"),
            ("Country 2017", "country"),
            ("pop punk", "punk"),
            ("country rock", "country"),
        ],
    )
    def test_matches_single_genre_titles(self, title, genre):
        assert mpd.genre_of(titled(1, title)) == genre

    @pytest.mark.parametrize(
        "title", ["indie metal", "classic rock & punk", "k-pop", "Throwbacks"]
    )
    def test_ambiguous_or_unrelated_titles_have_no_genre(self, title):
        assert mpd.genre_of(titled(1, title)) is None


class TestGenreSliceOrder:
    def test_pinned_slices_come_first_then_a_seeded_order(self):
        available = [f"mpd.slice.{i}.json" for i in range(10)] + list(mpd.SLICES)
        order = mpd.genre_slice_order(available)
        assert order[: len(mpd.SLICES)] == list(mpd.SLICES)
        assert sorted(order) == sorted(available)
        assert order == mpd.genre_slice_order(list(reversed(available)))


class TestGenreSampling:
    def test_groups_only_eligible_genre_playlists(self):
        playlists = [titled(1, "indie"), titled(2, "indie", size=3), titled(3, "Throwbacks")]
        grouped = mpd.eligible_by_genre(playlists)
        assert [p.playlist_mbid for p in grouped["indie"]] == ["mpd1"]
        assert all(not found for g, found in grouped.items() if g != "indie")

    def test_samples_up_to_the_limit_per_genre(self):
        grouped = mpd.eligible_by_genre([titled(i, "metal") for i in range(5)])
        sampled = mpd.sample_by_genre(grouped, 3)
        assert len(sampled["metal"]) == 3
        assert sampled == mpd.sample_by_genre(grouped, 3)

    def test_filled_needs_every_genre(self):
        grouped = {genre: [titled(1, "x")] for genre in mpd.GENRE_PATTERNS}
        assert mpd.genres_filled(grouped, 1)
        grouped["punk"] = []
        assert not mpd.genres_filled(grouped, 1)


class TestScanForGenres:
    def _slice(self, tmp_path, name, titles):
        path = tmp_path / name
        playlists = [{**varied(i), "name": t} for i, t in titles]
        path.write_text(json.dumps({"info": {}, "playlists": playlists}), encoding="utf-8")
        return path

    def test_stops_once_every_genre_is_filled(self, tmp_path):
        genres = list(mpd.GENRE_PATTERNS)
        first = self._slice(tmp_path, "a.json", [(i, g.replace("_", " ")) for i, g in enumerate(genres)])

        def never_needed():
            yield first
            raise AssertionError("the scan must stop before the second slice")

        scanned, grouped = mpd.scan_for_genres(never_needed(), per_genre=1)
        assert scanned == ["a.json"]
        assert mpd.genres_filled(grouped, 1)

    def test_respects_the_slice_cap(self, tmp_path):
        paths = [self._slice(tmp_path, f"{i}.json", [(i, "indie")]) for i in range(3)]
        scanned, _ = mpd.scan_for_genres(iter(paths), per_genre=5, max_slices=2)
        assert scanned == ["0.json", "1.json"]
