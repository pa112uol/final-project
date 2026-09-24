from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx

logger = logging.getLogger(__name__)

LB_API = "https://api.listenbrainz.org/1"
EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
DEFAULT_CATALOGUE_PATH = EVIDENCE_DIR / "playlist-catalogue.json"
# Every ListenBrainz response the build received, so a rerun resumes instead of restarting
DEFAULT_RESPONSE_CACHE_PATH = EVIDENCE_DIR / "listenbrainz-responses.json"
CACHE_FLUSH_EVERY = 50

# The playlist search endpoint times out at the ListenBrainz gateway, so users
# are found through the follow graph instead
ROOT_USERS = ("rob", "aerozol", "mr_monkey", "lucifer")
MAX_USERS = 400
PLAYLIST_PAGE_SIZE = 100
DEFAULT_PLAYLIST_LIMIT = 60
SAMPLE_SEED = 20260921
PROGRESS_EVERY_USERS = 25

MIN_TRACKS = 10
MIN_DISTINCT_ARTISTS = 5
# A playlist dominated by one artist is closer to a discography than a mix
MAX_ARTIST_SHARE = 0.5
MIN_HELD_OUT = 5

# ListenBrainz's own recommenders. Their playlists come from tag and listen
# similarity, which would make the ground truth echo a recommender
GENERATED_CREATORS = frozenset({"troi-bot", "listenbrainz"})
GENERATED_TITLE_PATTERN = re.compile(
    r"daily jams|weekly jams|weekly exploration|lb radio|top discoveries"
    r"|top missed recordings|year in music|copy of|exported xspf|created for",
    re.IGNORECASE,
)
# Markers of recommender output or of a copy of someone else's playlist
GENERATED_EXTENSION_KEYS = frozenset(
    {"algorithm_metadata", "created_for", "copied_from", "copied_from_deleted"}
)

PLAYLIST_EXTENSION = "https://musicbrainz.org/doc/jspf#playlist"
TRACK_EXTENSION = "https://musicbrainz.org/doc/jspf#track"

REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 6
MAX_BACKOFF_SECONDS = 60
RATE_LIMIT_FALLBACK_WAIT_SECONDS = 10
# Pauses while a request is still left in the window, before the server refuses one
RATE_LIMIT_HEADROOM = 1


# recording_mbid is empty for sources without MusicBrainz IDs. track_id is the
# source's own identifier, so every track still has a stable identity
@dataclass(frozen=True)
class PlaylistTrack:
    recording_mbid: str
    title: str
    artist: str
    artist_mbids: tuple[str, ...]
    track_id: str = ""

    @property
    def identity(self) -> str:
        return self.recording_mbid or self.track_id


@dataclass(frozen=True)
class Playlist:
    playlist_mbid: str
    title: str
    creator: str
    tracks: tuple[PlaylistTrack, ...]
    extension: dict = field(default_factory=dict, hash=False, compare=False)


# group names a subset the case was sampled for, such as a genre, and is
# empty for an unstratified sample
@dataclass(frozen=True)
class Case:
    case_id: str
    playlist_mbid: str
    creator_hash: str
    seeds: tuple[PlaylistTrack, ...]
    held_out: tuple[PlaylistTrack, ...]
    group: str = ""


class CatalogueIncomplete(RuntimeError):
    pass


def last_path_segment(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def hash_creator(creator: str) -> str:
    return hashlib.sha256(creator.casefold().encode()).hexdigest()[:12]


# An artist is identified by MBID where the playlist has one, else by name, so
# tracks without artist MBIDs can still be told apart
def artist_identity(track: PlaylistTrack) -> frozenset[str]:
    if track.artist_mbids:
        return frozenset(track.artist_mbids)
    return frozenset({track.artist.casefold()})


# Reads one JSPF track. Returns None when it has no recording MBID, since
# such a track can be neither a seed nor reliably matched
def parse_playlist_track(raw: dict) -> PlaylistTrack | None:
    identifiers = raw.get("identifier") or []
    if isinstance(identifiers, str):
        identifiers = [identifiers]
    recording_mbids = [
        last_path_segment(url) for url in identifiers if "/recording/" in url
    ]
    title = (raw.get("title") or "").strip()
    artist = (raw.get("creator") or "").strip()
    if not recording_mbids or not title or not artist:
        return None
    extension = (raw.get("extension") or {}).get(TRACK_EXTENSION) or {}
    artist_mbids = tuple(
        last_path_segment(url)
        for url in extension.get("artist_identifiers") or []
    )
    return PlaylistTrack(recording_mbids[0], title, artist, artist_mbids)


def parse_playlist(raw: dict) -> Playlist:
    tracks = tuple(
        track
        for entry in raw.get("track") or []
        if (track := parse_playlist_track(entry)) is not None
    )
    return Playlist(
        playlist_mbid=last_path_segment(raw.get("identifier", "")),
        title=raw.get("title") or "",
        creator=raw.get("creator") or "",
        tracks=tracks,
        extension=(raw.get("extension") or {}).get(PLAYLIST_EXTENSION) or {},
    )


# ListenBrainz nests some markers inside additional_metadata, so both levels are checked
def extension_keys(extension: dict) -> set[str]:
    nested = extension.get("additional_metadata") or {}
    return set(extension) | set(nested if isinstance(nested, dict) else ())


def is_generated(playlist: Playlist) -> bool:
    return (
        playlist.creator.casefold() in GENERATED_CREATORS
        or bool(GENERATED_TITLE_PATTERN.search(playlist.title))
        or bool(GENERATED_EXTENSION_KEYS & extension_keys(playlist.extension))
    )


# Largest fraction of a playlist's tracks credited to one artist
def max_artist_share(tracks: tuple[PlaylistTrack, ...]) -> float:
    counts: dict[frozenset[str], int] = {}
    for track in tracks:
        identity = artist_identity(track)
        counts[identity] = counts.get(identity, 0) + 1
    return max(counts.values()) / len(tracks) if tracks else 0.0


def distinct_artist_count(tracks: tuple[PlaylistTrack, ...]) -> int:
    return len({artist_identity(track) for track in tracks})


def is_eligible(playlist: Playlist) -> bool:
    return (
        not is_generated(playlist)
        and len(playlist.tracks) >= MIN_TRACKS
        and distinct_artist_count(playlist.tracks) >= MIN_DISTINCT_ARTISTS
        and max_artist_share(playlist.tracks) <= MAX_ARTIST_SHARE
    )


# Tracks by none of the seed artists, one per recording. The pipeline drops
# seed artists from its candidates, so their tracks could never be retrieved
def held_out_tracks(
    tracks: tuple[PlaylistTrack, ...], seeds: tuple[PlaylistTrack, ...]
) -> tuple[PlaylistTrack, ...]:
    seed_artists = set().union(*(artist_identity(seed) for seed in seeds))
    seen = {seed.identity for seed in seeds}
    kept = []
    for track in tracks:
        if track.identity in seen or artist_identity(track) & seed_artists:
            continue
        seen.add(track.identity)
        kept.append(track)
    return tuple(kept)


# The first block of a UUID, or the whole id when it has no hyphens
def case_prefix(playlist_id: str) -> str:
    return playlist_id.split("-", 1)[0]


# The one-seed case uses the first seed of the pair, so the two cases from a
# playlist differ only by the second seed
def build_cases(
    playlist: Playlist, sample_seed: int = SAMPLE_SEED, group: str = ""
) -> list[Case]:
    rng = random.Random(f"{sample_seed}:{playlist.playlist_mbid}")
    first = rng.choice(playlist.tracks)
    others = [
        track
        for track in playlist.tracks
        if not artist_identity(track) & artist_identity(first)
    ]
    if not others:
        return []
    second = rng.choice(others)
    creator_hash = hash_creator(playlist.creator)
    cases = []
    for seeds in ((first,), (first, second)):
        held_out = held_out_tracks(playlist.tracks, seeds)
        if len(held_out) < MIN_HELD_OUT:
            continue
        cases.append(
            Case(
                case_id=f"{case_prefix(playlist.playlist_mbid)}-{len(seeds)}seed",
                playlist_mbid=playlist.playlist_mbid,
                creator_hash=creator_hash,
                seeds=seeds,
                held_out=held_out,
                group=group,
            )
        )
    return cases


# Fixed-seed visiting order over users, independent of the order the walk found them
def sampling_order(
    users: list[str], sample_seed: int = SAMPLE_SEED
) -> list[str]:
    order = sorted(users, key=str.casefold)
    random.Random(sample_seed).shuffle(order)
    return order


def case_to_dict(case: Case) -> dict:
    return asdict(case)


def track_from_dict(data: dict) -> PlaylistTrack:
    return PlaylistTrack(
        recording_mbid=data["recording_mbid"],
        title=data["title"],
        artist=data["artist"],
        artist_mbids=tuple(data.get("artist_mbids") or ()),
        track_id=data.get("track_id", ""),
    )


def case_from_dict(data: dict) -> Case:
    return Case(
        case_id=data["case_id"],
        playlist_mbid=data["playlist_mbid"],
        creator_hash=data["creator_hash"],
        seeds=tuple(track_from_dict(seed) for seed in data["seeds"]),
        held_out=tuple(track_from_dict(track) for track in data["held_out"]),
        group=data.get("group", ""),
    )


def load_cases(path: Path) -> list[Case]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [case_from_dict(case) for case in payload["cases"]]


# Follows the X-RateLimit headers ListenBrainz sends on every response. When
# the window is nearly spent, the next request waits for the reset
class RateLimiter:
    def __init__(self, clock=time.monotonic, sleep=asyncio.sleep):
        self._clock = clock
        self._sleep = sleep
        self._resume_at = 0.0

    async def wait(self) -> None:
        delay = self._resume_at - self._clock()
        if delay > 0:
            await self._sleep(delay)

    async def pause(self, seconds: float) -> None:
        await self._sleep(seconds)

    def record(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_in = response.headers.get(
            "X-RateLimit-Reset-In", RATE_LIMIT_FALLBACK_WAIT_SECONDS
        )
        exhausted = response.status_code == 429 or (
            remaining is not None and int(remaining) <= RATE_LIMIT_HEADROOM
        )
        if exhausted:
            self._resume_at = self._clock() + float(reset_in)


# Stores response bodies by request, with None for a 404. Writes to disk every
# CACHE_FLUSH_EVERY new entries and on flush, so an aborted run keeps its progress
class ResponseCache:
    def __init__(self, path: Path | None = None):
        self._path = path
        self._entries: dict[str, dict | None] = {}
        self._unsaved = 0
        if path is not None and path.exists():
            self._entries = json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def key(path: str, params: dict) -> str:
        return f"{path}?{urlencode(sorted(params.items()))}"

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def get(self, key: str) -> dict | None:
        return self._entries[key]

    def put(self, key: str, body: dict | None) -> None:
        self._entries[key] = body
        self._unsaved += 1
        if self._unsaved >= CACHE_FLUSH_EVERY:
            self.flush()

    def flush(self) -> None:
        if self._path is None or not self._unsaved:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._entries), encoding="utf-8")
        self._unsaved = 0


# Usernames may contain ?, # or %, which would otherwise end or garble the path
def user_path(user: str, resource: str) -> str:
    return f"/user/{quote(user, safe='')}/{resource}"


def backoff_seconds(attempt: int) -> float:
    return float(min(2**attempt, MAX_BACKOFF_SECONDS))


# Sends one GET and returns (done, body, failure). done is False when the
# attempt should be retried, and failure then says why
async def attempt_request(
    client: httpx.AsyncClient, limiter: RateLimiter, path: str, params: dict
) -> tuple[bool, dict | None, str]:
    await limiter.wait()
    try:
        response = await client.get(f"{LB_API}{path}", params=params)
    except httpx.TransportError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"
    limiter.record(response)
    if response.status_code == 404:
        return True, None, ""
    if response.status_code == 429 or response.status_code >= 500:
        return False, None, f"HTTP {response.status_code}"
    if response.is_error:
        raise CatalogueIncomplete(
            f"{path} returned HTTP {response.status_code}"
        )
    try:
        return True, response.json(), ""
    except ValueError:
        return False, None, "HTTP 200 with an empty or invalid JSON body"


# GET through the cache and the limiter. Timeouts, dropped connections, server
# errors and unreadable bodies are retried with backoff. Returns None on 404
async def fetch_json(
    client: httpx.AsyncClient,
    limiter: RateLimiter,
    path: str,
    params: dict,
    cache: ResponseCache | None = None,
) -> dict | None:
    cache = cache if cache is not None else ResponseCache()
    key = ResponseCache.key(path, params)
    if key in cache:
        return cache.get(key)
    failure = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        done, body, failure = await attempt_request(
            client, limiter, path, params
        )
        if done:
            cache.put(key, body)
            return body
        # A 429 already set the limiter to wait for the reset window
        if failure != "HTTP 429":
            await limiter.pause(backoff_seconds(attempt))
    raise CatalogueIncomplete(
        f"{path} failed {MAX_ATTEMPTS} times, last: {failure}"
    )


async def fetch_neighbours(
    client: httpx.AsyncClient,
    limiter: RateLimiter,
    user: str,
    cache: ResponseCache,
) -> list[str]:
    neighbours = []
    for relation in ("followers", "following"):
        data = await fetch_json(
            client, limiter, user_path(user, relation), {}, cache
        )
        neighbours.extend((data or {}).get(relation) or [])
    return neighbours


# MBIDs of every playlist the user created, read page by page, with generated
# playlists and copies removed from the headers. None when the API cannot serve them
async def fetch_own_playlist_mbids(
    client: httpx.AsyncClient,
    limiter: RateLimiter,
    user: str,
    cache: ResponseCache,
) -> list[str] | None:
    mbids = []
    offset = 0
    while True:
        data = await fetch_json(
            client,
            limiter,
            user_path(user, "playlists"),
            {"count": PLAYLIST_PAGE_SIZE, "offset": offset},
            cache,
        )
        # ListenBrainz decodes %2F in a username and 404s, so such users are unreachable
        if data is None:
            return None if offset == 0 else mbids
        entries = data.get("playlists") or []
        for entry in entries:
            header = parse_playlist(entry["playlist"])
            if not is_generated(header):
                mbids.append(header.playlist_mbid)
        offset += len(entries)
        if not entries or offset >= data.get("playlist_count", 0):
            return mbids


# Breadth-first walk over followers and following. Neighbours are sorted so
# the walk, and therefore the user set, is the same on every run
async def discover_users(
    client: httpx.AsyncClient,
    limiter: RateLimiter,
    cache: ResponseCache,
    roots: tuple[str, ...] = ROOT_USERS,
    max_users: int = MAX_USERS,
) -> dict[str, list[str] | None]:
    queue = list(roots)
    seen = {user.casefold() for user in roots}
    candidates: dict[str, list[str] | None] = {}
    while queue and len(candidates) < max_users:
        user = queue.pop(0)
        candidates[user] = await fetch_own_playlist_mbids(
            client, limiter, user, cache
        )
        for neighbour in sorted(
            await fetch_neighbours(client, limiter, user, cache)
        ):
            if neighbour.casefold() not in seen:
                seen.add(neighbour.casefold())
                queue.append(neighbour)
        if len(candidates) % PROGRESS_EVERY_USERS == 0:
            logger.info("visited %d users", len(candidates))
    return candidates


async def fetch_playlist(
    client: httpx.AsyncClient,
    limiter: RateLimiter,
    playlist_mbid: str,
    cache: ResponseCache,
) -> Playlist | None:
    data = await fetch_json(
        client, limiter, f"/playlist/{quote(playlist_mbid, safe='')}", {}, cache
    )
    return None if data is None else parse_playlist(data["playlist"])


# Takes each user's first eligible playlist in a seeded order, one per user,
# until the limit is reached. Returns the playlists and how many were fetched
async def pick_playlists(
    client: httpx.AsyncClient,
    limiter: RateLimiter,
    cache: ResponseCache,
    candidates: dict[str, list[str] | None],
    limit: int,
    sample_seed: int = SAMPLE_SEED,
) -> tuple[list[Playlist], int]:
    picked: list[Playlist] = []
    fetched = 0
    for user in sampling_order(list(candidates), sample_seed):
        if len(picked) >= limit:
            break
        mbids = sorted(candidates[user] or [])
        random.Random(f"{sample_seed}:{user.casefold()}").shuffle(mbids)
        for mbid in mbids:
            playlist = await fetch_playlist(client, limiter, mbid, cache)
            fetched += 1
            if playlist is not None and is_eligible(playlist):
                picked.append(playlist)
                break
    return picked, fetched


def catalogue_payload(
    candidates: dict[str, list[str] | None],
    fetched: int,
    picked: list[Playlist],
    cases: list[Case],
) -> dict:
    return {
        "method": {
            "source": "ListenBrainz public playlists created by the user",
            "discovery": "breadth-first walk over followers and following",
            "root_users": list(ROOT_USERS),
            "max_users": MAX_USERS,
            "sample_seed": SAMPLE_SEED,
            "excluded": "recommender output and copies of other playlists",
            "min_tracks": MIN_TRACKS,
            "min_distinct_artists": MIN_DISTINCT_ARTISTS,
            "max_artist_share": MAX_ARTIST_SHARE,
            "min_held_out": MIN_HELD_OUT,
            "creators": "one playlist per creator, SHA-256 hashed",
        },
        "counts": {
            "visited_users": len(candidates),
            "users_with_unreachable_playlists": sum(
                m is None for m in candidates.values()
            ),
            "users_with_own_playlists": sum(
                bool(m) for m in candidates.values()
            ),
            "fetched_playlists": fetched,
            "picked_playlists": len(picked),
            "cases": len(cases),
            "one_seed_cases": sum(len(c.seeds) == 1 for c in cases),
            "two_seed_cases": sum(len(c.seeds) == 2 for c in cases),
        },
        "cases": [case_to_dict(case) for case in cases],
    }


async def build_catalogue(limit: int, cache: ResponseCache) -> dict:
    limiter = RateLimiter()
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            candidates = await discover_users(client, limiter, cache)
            picked, fetched = await pick_playlists(
                client, limiter, cache, candidates, limit
            )
    finally:
        cache.flush()
    cases = [case for playlist in picked for case in build_cases(playlist)]
    return catalogue_payload(candidates, fetched, picked, cases)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlists", type=int, default=DEFAULT_PLAYLIST_LIMIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_CATALOGUE_PATH)
    parser.add_argument(
        "--response-cache", type=Path, default=DEFAULT_RESPONSE_CACHE_PATH
    )
    args = parser.parse_args()
    cache = ResponseCache(args.response_cache)
    try:
        payload = asyncio.run(build_catalogue(max(1, args.playlists), cache))
    except CatalogueIncomplete as exc:
        raise SystemExit(
            f"catalogue not written, a request failed: {exc}. "
            "Rerun to resume from the saved responses"
        ) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("%s", json.dumps(payload["counts"]))
    logger.info("wrote %s", args.output)


if __name__ == "__main__":
    main()
