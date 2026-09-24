from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
from pathlib import Path

import httpx

from evaluation.playlist_catalogue import (
    EVIDENCE_DIR,
    MAX_ARTIST_SHARE,
    MIN_DISTINCT_ARTISTS,
    MIN_HELD_OUT,
    MIN_TRACKS,
    SAMPLE_SEED,
    Case,
    Playlist,
    PlaylistTrack,
    build_cases,
    case_to_dict,
    is_eligible,
)

logger = logging.getLogger(__name__)

MIRROR_LISTING_URL = (
    "https://api.github.com/repos/DevinOgrady/spotify_million_playlist_dataset"
    "/contents/data1"
)
MIRROR_BASE = "https://raw.githubusercontent.com/DevinOgrady/spotify_million_playlist_dataset/main"
SLICE_URL = f"{MIRROR_BASE}/data1/{{name}}"
MD5SUMS_URL = f"{MIRROR_BASE}/md5sums"
DEFAULT_SLICE_DIR = EVIDENCE_DIR / "mpd"
DEFAULT_CATALOGUE_PATH = EVIDENCE_DIR / "mpd-catalogue.json"
DEFAULT_GENRE_CATALOGUE_PATH = EVIDENCE_DIR / "mpd-genre-catalogue.json"

# Drawn once with SAMPLE_SEED from the 284 slices the mirror holds, then pinned
SLICES = (
    "mpd.slice.622000-622999.json",
    "mpd.slice.420000-420999.json",
    "mpd.slice.492000-492999.json",
)
DEFAULT_PLAYLIST_LIMIT = 100
DEFAULT_PER_GENRE = 30
MAX_GENRE_SLICES = 40

# Matched against playlist titles. pop needs a bare "pop" title, so "pop punk"
# counts as punk. A title matching two patterns, such as "indie metal", is skipped
GENRE_PATTERNS = {
    "classic_rock": re.compile(r"classic\s*rock", re.IGNORECASE),
    "indie": re.compile(r"\bindie\b", re.IGNORECASE),
    "metal": re.compile(r"\bmetal\b", re.IGNORECASE),
    "punk": re.compile(r"\bpunk\b", re.IGNORECASE),
    "pop": re.compile(
        r"^\W*pop(\s+(hits|music|songs|mix|playlist))?\W*$", re.IGNORECASE
    ),
    "country": re.compile(r"\bcountry\b", re.IGNORECASE),
    "electronic": re.compile(
        r"\bedm\b|\belectronic\b|\belectro\b|\bhouse\b|\btechno\b"
        r"|\bdubstep\b|\btrance\b",
        re.IGNORECASE,
    ),
}
DOWNLOAD_TIMEOUT_SECONDS = 300
MD5_CHUNK_BYTES = 1 << 20


class SliceVerificationError(RuntimeError):
    pass


# Reads lines of the form "<md5>  data/<file name>" into a name to hash map
def parse_md5sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[Path(parts[1]).name] = parts[0]
    return sums


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while chunk := handle.read(MD5_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def verify_slice(path: Path, expected_md5: str) -> None:
    actual = file_md5(path)
    if actual != expected_md5:
        raise SliceVerificationError(
            f"{path.name} has md5 {actual}, the official release has {expected_md5}"
        )


# Downloads to a temporary name and renames only after the hash matches, so
# a partial or altered file never sits where a verified one is expected
def download_slice(
    client: httpx.Client, name: str, directory: Path, expected_md5: str
) -> Path:
    target = directory / name
    if target.exists():
        verify_slice(target, expected_md5)
        return target
    directory.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    with client.stream("GET", SLICE_URL.format(name=name)) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    try:
        verify_slice(partial, expected_md5)
    except SliceVerificationError:
        partial.unlink()
        raise
    partial.replace(target)
    return target


def fetch_md5sums(client: httpx.Client) -> dict[str, str]:
    response = client.get(MD5SUMS_URL)
    response.raise_for_status()
    return parse_md5sums(response.text)


# MPD tracks carry Spotify URIs rather than MusicBrainz IDs, so the URI
# becomes the track identity and artists are told apart by name
def parse_mpd_track(raw: dict) -> PlaylistTrack | None:
    title = (raw.get("track_name") or "").strip()
    artist = (raw.get("artist_name") or "").strip()
    uri = raw.get("track_uri") or ""
    if not title or not artist or not uri:
        return None
    return PlaylistTrack(
        recording_mbid="",
        title=title,
        artist=artist,
        artist_mbids=(),
        track_id=uri,
    )


# The dataset is anonymised, so the playlist id stands in for the creator
def parse_mpd_playlist(raw: dict) -> Playlist:
    playlist_id = f"mpd{raw['pid']}"
    tracks = tuple(
        track
        for entry in sorted(
            raw.get("tracks") or [], key=lambda t: t.get("pos", 0)
        )
        if (track := parse_mpd_track(entry)) is not None
    )
    return Playlist(
        playlist_mbid=playlist_id,
        title=raw.get("name") or "",
        creator=playlist_id,
        tracks=tracks,
    )


def load_slice(path: Path) -> list[Playlist]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [parse_mpd_playlist(raw) for raw in payload["playlists"]]


def sample_eligible(
    playlists: list[Playlist], limit: int, sample_seed: int = SAMPLE_SEED
) -> list[Playlist]:
    eligible = sorted(
        (p for p in playlists if is_eligible(p)), key=lambda p: p.playlist_mbid
    )
    random.Random(sample_seed).shuffle(eligible)
    return eligible[:limit]


# The genre whose pattern alone matches the title, or None for none or several
def genre_of(playlist: Playlist) -> str | None:
    matches = [
        genre
        for genre, pattern in GENRE_PATTERNS.items()
        if pattern.search(playlist.title)
    ]
    return matches[0] if len(matches) == 1 else None


# The pinned unstratified slices first, since they are already on disk, then
# every other mirror slice in a fixed-seed order
def genre_slice_order(
    available: list[str], sample_seed: int = SAMPLE_SEED
) -> list[str]:
    rest = sorted(name for name in available if name not in SLICES)
    random.Random(sample_seed).shuffle(rest)
    return [name for name in SLICES if name in available] + rest


# Eligible playlists per genre, each list sorted by id so the later sample does
# not depend on the order slices were read
def eligible_by_genre(playlists: list[Playlist]) -> dict[str, list[Playlist]]:
    grouped: dict[str, list[Playlist]] = {genre: [] for genre in GENRE_PATTERNS}
    for playlist in playlists:
        genre = genre_of(playlist)
        if genre is not None and is_eligible(playlist):
            grouped[genre].append(playlist)
    return {
        genre: sorted(found, key=lambda p: p.playlist_mbid)
        for genre, found in grouped.items()
    }


def sample_by_genre(
    grouped: dict[str, list[Playlist]],
    per_genre: int,
    sample_seed: int = SAMPLE_SEED,
) -> dict[str, list[Playlist]]:
    sampled = {}
    for genre, found in grouped.items():
        order = list(found)
        random.Random(f"{sample_seed}:{genre}").shuffle(order)
        sampled[genre] = order[:per_genre]
    return sampled


def genres_filled(grouped: dict[str, list[Playlist]], per_genre: int) -> bool:
    return all(len(found) >= per_genre for found in grouped.values())


def catalogue_payload(
    loaded: list[Playlist], sampled: list[Playlist], cases: list[Case]
) -> dict:
    return {
        "method": {
            "source": "Spotify Million Playlist Dataset (Chen et al., 2018)",
            "slices": list(SLICES),
            "verification": "md5 of every slice matches the official md5sums",
            "sample_seed": SAMPLE_SEED,
            "min_tracks": MIN_TRACKS,
            "min_distinct_artists": MIN_DISTINCT_ARTISTS,
            "max_artist_share": MAX_ARTIST_SHARE,
            "min_held_out": MIN_HELD_OUT,
            "matching": "normalised artist and title, the dataset has no MBIDs",
        },
        "counts": {
            "loaded_playlists": len(loaded),
            "eligible_playlists": sum(is_eligible(p) for p in loaded),
            "sampled_playlists": len(sampled),
            "cases": len(cases),
            "one_seed_cases": sum(len(c.seeds) == 1 for c in cases),
            "two_seed_cases": sum(len(c.seeds) == 2 for c in cases),
        },
        "cases": [case_to_dict(case) for case in cases],
    }


def genre_catalogue_payload(
    scanned: list[str],
    grouped: dict[str, list[Playlist]],
    sampled: dict[str, list[Playlist]],
    cases: list[Case],
) -> dict:
    return {
        "method": {
            "source": "Spotify Million Playlist Dataset (Chen et al., 2018)",
            "stratification": "playlist title matches exactly one genre pattern",
            "genre_patterns": {g: p.pattern for g, p in GENRE_PATTERNS.items()},
            "slices_scanned": scanned,
            "verification": "md5 of every slice matches the official md5sums",
            "sample_seed": SAMPLE_SEED,
            "min_tracks": MIN_TRACKS,
            "min_distinct_artists": MIN_DISTINCT_ARTISTS,
            "max_artist_share": MAX_ARTIST_SHARE,
            "min_held_out": MIN_HELD_OUT,
        },
        "counts": {
            "slices_scanned": len(scanned),
            "eligible_per_genre": {
                g: len(found) for g, found in grouped.items()
            },
            "sampled_per_genre": {
                g: len(found) for g, found in sampled.items()
            },
            "cases": len(cases),
        },
        "cases": [case_to_dict(case) for case in cases],
    }


def build_catalogue(slice_paths: list[Path], limit: int) -> dict:
    loaded = [playlist for path in slice_paths for playlist in load_slice(path)]
    sampled = sample_eligible(loaded, limit)
    cases = [case for playlist in sampled for case in build_cases(playlist)]
    return catalogue_payload(loaded, sampled, cases)


def fetch_mirror_slice_names(client: httpx.Client) -> list[str]:
    response = client.get(MIRROR_LISTING_URL)
    response.raise_for_status()
    return [
        entry["name"]
        for entry in response.json()
        if entry["name"].endswith(".json")
    ]


# Reads slices in order until every genre has per_genre eligible playlists or
# max_slices is reached. Returns the slices read and the eligible playlists
def scan_for_genres(
    slice_paths,
    per_genre: int,
    max_slices: int = MAX_GENRE_SLICES,
) -> tuple[list[str], dict[str, list[Playlist]]]:
    scanned: list[str] = []
    playlists: list[Playlist] = []
    grouped = eligible_by_genre([])
    for path in slice_paths:
        if len(scanned) >= max_slices:
            break
        playlists.extend(p for p in load_slice(path) if genre_of(p) is not None)
        scanned.append(path.name)
        grouped = eligible_by_genre(playlists)
        logger.info(
            "%s: %s", path.name, {g: len(found) for g, found in grouped.items()}
        )
        if genres_filled(grouped, per_genre):
            break
    return scanned, grouped


def build_genre_catalogue(directory: Path, per_genre: int) -> dict:
    with httpx.Client(
        timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        sums = fetch_md5sums(client)
        available = [n for n in fetch_mirror_slice_names(client) if n in sums]
        # A generator, so each slice is downloaded only once the scan needs it
        paths = (
            download_slice(client, name, directory, sums[name])
            for name in genre_slice_order(available)
        )
        scanned, grouped = scan_for_genres(paths, per_genre)
    sampled = sample_by_genre(grouped, per_genre)
    cases = [
        case
        for genre, playlists in sampled.items()
        for playlist in playlists
        for case in build_cases(playlist, group=genre)
    ]
    return genre_catalogue_payload(scanned, grouped, sampled, cases)


def fetch_verified_slices(directory: Path) -> list[Path]:
    with httpx.Client(
        timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
    ) as client:
        sums = fetch_md5sums(client)
        missing = [name for name in SLICES if name not in sums]
        if missing:
            raise SliceVerificationError(
                f"no official md5 for {', '.join(missing)}"
            )
        return [
            download_slice(client, name, directory, sums[name])
            for name in SLICES
        ]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlists", type=int, default=DEFAULT_PLAYLIST_LIMIT)
    parser.add_argument("--slice-dir", type=Path, default=DEFAULT_SLICE_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--by-genre", action="store_true")
    parser.add_argument("--per-genre", type=int, default=DEFAULT_PER_GENRE)
    args = parser.parse_args()
    try:
        if args.by_genre:
            output = args.output or DEFAULT_GENRE_CATALOGUE_PATH
            payload = build_genre_catalogue(
                args.slice_dir, max(1, args.per_genre)
            )
        else:
            output = args.output or DEFAULT_CATALOGUE_PATH
            slice_paths = fetch_verified_slices(args.slice_dir)
            payload = build_catalogue(slice_paths, max(1, args.playlists))
    except (httpx.HTTPError, SliceVerificationError) as exc:
        raise SystemExit(f"catalogue not written: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("%s", json.dumps(payload["counts"]))
    logger.info("wrote %s", output)


if __name__ == "__main__":
    main()
