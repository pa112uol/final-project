import asyncio
import math
import logging
import os
from .types import Candidate
from .constants import ARTISTS_PER_TAG, TOP_ARTISTS_COUNT, TRACKS_PER_ARTIST
from .utils import get_field

logger = logging.getLogger(__name__)

LB_CONCURRENCY = 5

# RECORDING_SOURCE env var controls which source fetch_recordings_for_artist
# uses for track discovery: "listenbrainz" (default) or "lastfm". Whichever is
# selected is used exclusively, with no fallback to the other.
RECORDING_SOURCES = ("listenbrainz", "lastfm")


def _recording_source():
    value = os.environ.get("RECORDING_SOURCE", "listenbrainz").strip().lower()
    return value if value in RECORDING_SOURCES else "listenbrainz"


# Artists ranked higher in tag.getTopArtists are stronger genre representatives.
# An NDCG style log discount weights rank 1 at 1.0 and rank 30 at 0.20
def _rank_decay(rank):
    return 1 / math.log2(rank + 2)


async def accumulate_artist_scores_from_tag_page(
    tag, tag_weight, page_idx, api_key, clients, artist_scores, artist_tags
):
    try:
        artists = await clients.fetch_tag_artists(
            tag, page_idx + 1, ARTISTS_PER_TAG, api_key
        )
        for rank, artist in enumerate(artists):
            name = get_field(artist, "name")
            mbid = get_field(artist, "mbid")
            key = name.lower()
            if key not in artist_tags:
                artist_tags[key] = set()
            # Guard against crediting the same tag twice if an artist appears
            # on multiple pages of the same tag result.
            tag_already_credited = tag in artist_tags[key]
            artist_tags[key].add(tag)
            rank_decay = _rank_decay(rank)
            if key in artist_scores:
                if not tag_already_credited:
                    artist_scores[key]["tag_weight_sum"] += (
                        tag_weight * rank_decay
                    )
                if not artist_scores[key]["mbid"] and mbid:
                    artist_scores[key]["mbid"] = mbid
            else:
                artist_scores[key] = {
                    "name": name,
                    "tag_weight_sum": tag_weight * rank_decay,
                    "mbid": mbid or "",
                }
    except Exception as exc:
        logger.warning("[candidates] fetch_tag_artists failed: %s", exc)


async def score_artists_across_all_tag_pages(
    top_tags, pages_to_fetch, api_key, clients
):
    artist_scores = {}
    artist_tags = {}
    fetch_tasks = [
        accumulate_artist_scores_from_tag_page(
            tag,
            tag_weight,
            page_idx,
            api_key,
            clients,
            artist_scores,
            artist_tags,
        )
        for tag, tag_weight in top_tags
        for page_idx in range(pages_to_fetch)
    ]
    await asyncio.gather(*fetch_tasks)
    return artist_scores, artist_tags


# Resolve missing artist MBIDs via MusicBrainz (serialised by mb_fetch queue).
async def resolve_artist_mbid_if_missing(artist, clients):
    if not artist["mbid"]:
        resolved = await clients.resolve_artist_mbid(artist["name"])
        artist["mbid"] = resolved
        logger.info(
            "[candidates] resolved mbid for %s: %s",
            artist["name"],
            resolved or "not found",
        )


async def resolve_missing_mbids_for_artists(top_artists, clients):
    await asyncio.gather(
        *[
            resolve_artist_mbid_if_missing(artist, clients)
            for artist in top_artists
        ]
    )


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# Normalises a raw Last.fm artist.getTopTracks entry into the same recording
# shape ListenBrainz's top-recordings-for-artist returns, so downstream code
# (get_field lookups, Candidate construction) doesn't need to know the source.
def _lastfm_track_to_recording(track, fallback_artist_mbid):
    title = get_field(track, "name")
    if not title:
        return None
    artist_field = get_field(track, "artist") or {}
    return {
        "mbid": get_field(track, "mbid") or "",
        "title": title,
        "artist_mbid": get_field(artist_field, "mbid") or fallback_artist_mbid,
        "duration_ms": None,
        "listen_count": _to_int(get_field(track, "playcount")),
        "user_count": _to_int(get_field(track, "listeners")),
        "tags": [],
    }


async def fetch_recordings_for_artist(
    artist, clients, sem, artist_tags, candidates, api_key
):
    if not artist["mbid"]:
        return
    source = _recording_source()
    async with sem:
        if source == "lastfm":
            try:
                lastfm_tracks = await clients.fetch_artist_top_tracks(
                    artist["name"], TRACKS_PER_ARTIST, api_key
                )
                recordings = [
                    recording
                    for t in lastfm_tracks
                    if (recording := _lastfm_track_to_recording(t, artist["mbid"]))
                ]
            except Exception as exc:
                logger.warning(
                    "[candidates] fetch_artist_top_tracks failed for %s: %s",
                    artist["name"],
                    exc,
                )
                recordings = []
        else:
            try:
                recordings = await clients.fetch_artist_top_recordings(
                    artist["mbid"], TRACKS_PER_ARTIST
                )
            except Exception as exc:
                logger.warning(
                    "[candidates] fetch_artist_top_recordings failed for %s: %s",
                    artist["mbid"],
                    exc,
                )
                recordings = []

    artist_key = artist["name"].lower()
    matched_tags = list(artist_tags.get(artist_key, set()))
    for recording in recordings:
        mbid = get_field(recording, "mbid")
        title = get_field(recording, "title")
        artist_mbid = get_field(recording, "artist_mbid")
        duration_ms = get_field(recording, "duration_ms")
        listen_count = get_field(recording, "listen_count")
        user_count = get_field(recording, "user_count")
        tags = get_field(recording, "tags")
        candidate_key = f"{title.lower()}|||{artist['name'].lower()}"
        candidates[candidate_key] = Candidate(
            title=title,
            artist=artist["name"],
            artist_mbid=artist_mbid,
            mbid=mbid,
            duration_ms=duration_ms,
            tag_weight_sum=artist["tag_weight_sum"],
            track_tag_score=0,
            listen_count=listen_count,
            user_count=user_count,
            artist_listen_count=0,
            tags=tags if tags else matched_tags,
        )


async def fetch_recordings_for_all_artists(top_artists, clients, artist_tags, api_key):
    candidates = {}
    sem = asyncio.Semaphore(LB_CONCURRENCY)
    await asyncio.gather(
        *[
            fetch_recordings_for_artist(
                artist, clients, sem, artist_tags, candidates, api_key
            )
            for artist in top_artists
        ]
    )
    return candidates


async def build_candidates(
    top_tags: list,
    api_key: str,
    novelty: float,
    clients,
) -> list:
    if not top_tags:
        return []

    # At higher novelty fetch deeper pages of tag.getTopArtists so the long
    # tail of less popular artists enters the pool. Page 1 is always included
    # so relevant artists are never dropped at any novelty level
    pages_to_fetch = 1 + round(novelty * 2)  # 1-3 pages
    top_artists_count = round(TOP_ARTISTS_COUNT * (1 + novelty))  # 15-30

    # Phase A: score artists by how many weighted tags they appear in
    artist_scores, artist_tags = await score_artists_across_all_tag_pages(
        top_tags, pages_to_fetch, api_key, clients
    )

    all_scored_artists = sorted(
        artist_scores.values(),
        key=lambda artist: (-artist["tag_weight_sum"], artist["name"]),
    )
    logger.info(
        "[candidates] scored artists total:%d, selecting top:%d (novelty pages:%d)",
        len(all_scored_artists),
        top_artists_count,
        pages_to_fetch,
    )
    top_artists = all_scored_artists[:top_artists_count]
    logger.info(
        "[candidates] top artists: %s",
        ", ".join(
            f"{a['name']}({a['tag_weight_sum']:.0f})" for a in top_artists
        ),
    )

    await resolve_missing_mbids_for_artists(top_artists, clients)

    # Phase B: fetch top recordings from ListenBrainz: verified MBIDs + listen counts
    candidates = await fetch_recordings_for_all_artists(
        top_artists, clients, artist_tags, api_key
    )

    result = list(candidates.values())
    logger.info("[candidates] total recordings fetched:%d", len(result))
    return result
