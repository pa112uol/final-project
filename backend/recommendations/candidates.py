import asyncio
import math
import logging
from .types import Candidate
from .constants import ARTISTS_PER_TAG, TOP_ARTISTS_COUNT, TRACKS_PER_ARTIST

logger = logging.getLogger(__name__)

LB_CONCURRENCY = 5


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
    # so relevant artists are never dropped at any novelty level.
    pages_to_fetch = 1 + round(novelty * 2)  # 1-3 pages
    top_artists_count = round(TOP_ARTISTS_COUNT * (1 + novelty))  # 15-30

    # Phase A: score artists by how many weighted tags they appear in
    artist_scores = {}
    artist_tags = {}

    async def fetch_tag_page(tag, tag_weight, page_idx):
        try:
            artists = await clients.fetch_tag_artists(
                tag, page_idx + 1, ARTISTS_PER_TAG, api_key
            )
            for rank, artist in enumerate(artists):
                name = artist.name if hasattr(artist, "name") else artist["name"]
                mbid = (
                    artist.mbid
                    if hasattr(artist, "mbid")
                    else artist.get("mbid")
                )
                key = name.lower()
                if key not in artist_tags:
                    artist_tags[key] = set()
                # Guard against crediting the same tag twice if an artist appears
                # on multiple pages of the same tag result.
                tag_already_credited = tag in artist_tags[key]
                artist_tags[key].add(tag)
                # Artists ranked higher in tag.getTopArtists are stronger genre
                # representatives. Applying an NDCG style log discount weights rank 1
                # at 1.0 and rank 30 at 0.20.
                rank_decay = 1 / math.log2(rank + 2)
                if key in artist_scores:
                    if not tag_already_credited:
                        artist_scores[key]["tag_weight_sum"] += tag_weight * rank_decay
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

    fetch_tasks = [
        fetch_tag_page(tag, tag_weight, page_idx)
        for tag, tag_weight in top_tags
        for page_idx in range(pages_to_fetch)
    ]
    await asyncio.gather(*fetch_tasks)

    all_scored_artists = sorted(
        artist_scores.values(),
        key=lambda a: (-a["tag_weight_sum"], a["name"]),
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

    # Resolve missing artist MBIDs via MusicBrainz (serialised by mb_fetch queue)
    async def resolve_mbid(artist):
        if not artist["mbid"]:
            resolved = await clients.resolve_artist_mbid(artist["name"])
            artist["mbid"] = resolved
            logger.info(
                "[candidates] resolved mbid for %s: %s",
                artist["name"],
                resolved or "not found",
            )

    await asyncio.gather(*[resolve_mbid(a) for a in top_artists])

    # Phase B: fetch top recordings from ListenBrainz: verified MBIDs + listen counts
    candidates = {}
    sem = asyncio.Semaphore(LB_CONCURRENCY)

    async def fetch_recordings(artist):
        if not artist["mbid"]:
            return
        async with sem:
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
                return

        key_lower = artist["name"].lower()
        matched_tags = list(artist_tags.get(key_lower, set()))
        for r in recordings:
            r_mbid = r.mbid if hasattr(r, "mbid") else r["mbid"]
            r_title = r.title if hasattr(r, "title") else r["title"]
            r_artist_mbid = (
                r.artist_mbid if hasattr(r, "artist_mbid") else r["artist_mbid"]
            )
            r_duration = (
                r.duration_ms if hasattr(r, "duration_ms") else r.get("duration_ms")
            )
            r_listen_count = (
                r.listen_count if hasattr(r, "listen_count") else r["listen_count"]
            )
            r_user_count = (
                r.user_count if hasattr(r, "user_count") else r["user_count"]
            )
            r_tags = r.tags if hasattr(r, "tags") else r["tags"]
            cand_key = f"{r_title.lower()}|||{artist['name'].lower()}"
            candidates[cand_key] = Candidate(
                title=r_title,
                artist=artist["name"],
                artist_mbid=r_artist_mbid,
                mbid=r_mbid,
                duration_ms=r_duration,
                tag_weight_sum=artist["tag_weight_sum"],
                track_tag_score=0,
                listen_count=r_listen_count,
                user_count=r_user_count,
                artist_listen_count=0,
                tags=r_tags if r_tags else matched_tags,
            )

    await asyncio.gather(*[fetch_recordings(a) for a in top_artists])

    result = list(candidates.values())
    logger.info("[candidates] total recordings fetched:%d", len(result))
    return result
