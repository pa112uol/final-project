import asyncio
import logging
from .types import Seed, Track
from .candidates import build_candidates
from .tags import (
    build_tag_weights,
    merge_tags,
    MOOD_TAGS,
    normalize_tag,
    is_noise_tag,
    BROAD_FETCH_TAGS,
)
from .dedup import filter_seeds, deduplicate_by_mbid, deduplicate_by_title
from .scoring import score_and_sort
from .diversify import mmr_select
from .constants import (
    RECOMMENDATION_LIMIT,
    TOP_TAGS_COUNT,
    MOOD_MULTIPLIER,
    MAX_TRACKS_PER_ARTIST,
)

logger = logging.getLogger(__name__)


async def run_pipeline(
    seeds: list,
    api_key: str,
    mood,
    novelty: float,
    clients,
    exclude_seed_artists: bool = True,
) -> list:
    logger.info(
        "[pipeline:entry] seeds:%d mood:%s novelty:%s  %s",
        len(seeds),
        mood if mood else "none",
        novelty,
        ", ".join(
            f'"{s.title if isinstance(s, Seed) else s["title"]}"'
            f' by {s.artist if isinstance(s, Seed) else s["artist"]}'
            for s in seeds
        ),
    )

    async def profile_seed(s):
        mbid = s.mbid if isinstance(s, Seed) else s["mbid"]
        title = s.title if isinstance(s, Seed) else s["title"]
        artist = s.artist if isinstance(s, Seed) else s["artist"]
        lb_task = (
            clients.fetch_recording_tags(mbid) if mbid else asyncio.sleep(0, result=[])
        )
        lf_task = clients.fetch_track_tags(title, artist, api_key, mbid or None)
        lb_tags, lf_tags = await asyncio.gather(lb_task, lf_task)
        logger.info(
            "lf_tags for %s: %s",
            title,
            ", ".join(
                f"{t.name if hasattr(t, 'name') else t['name']}"
                f"({t.count if hasattr(t, 'count') else t['count']})"
                for t in lf_tags
            ) or "(none)",
        )
        logger.info(
            "lb_tags for %s: %s",
            title,
            ", ".join(
                f"{t['name'] if isinstance(t, dict) else t.name}"
                f"({t['count'] if isinstance(t, dict) else t.count})"
                for t in lb_tags
            ) or "(none)",
        )
        return merge_tags(lb_tags, lf_tags)

    seed_tag_sets = await asyncio.gather(*[profile_seed(s) for s in seeds])

    tag_weights = build_tag_weights(seed_tag_sets)
    sorted_tags = sorted(tag_weights.items(), key=lambda x: -x[1])

    if not sorted_tags:
        return []

    # Exclude tags that match a seed artist name, e.g. "queen" for a Queen seed
    # would make fetch_tag_artists return mostly Queen members and collaborators.
    seed_artist_names = {
        (s.artist.lower() if isinstance(s, Seed) else s["artist"].lower())
        for s in seeds
    }

    # Prefer specific tags for fetching. Fallback to broad ones only when
    # fewer than 2 specific tags exist (e.g. a pure rock seed with no sub-genre).
    fetch_tags = [
        (tag, w)
        for tag, w in sorted_tags
        if (
            normalize_tag(tag) not in BROAD_FETCH_TAGS
            and tag not in seed_artist_names
            and not is_noise_tag(tag)
        )
    ][:TOP_TAGS_COUNT]

    if len(fetch_tags) < 2:
        fetch_tags = [
            (tag, w)
            for tag, w in sorted_tags
            if tag not in seed_artist_names and not is_noise_tag(tag)
        ][:TOP_TAGS_COUNT]

    logger.info(
        "[tags] fetch tags: %s",
        ", ".join(f"{t}({w:.0f})" for t, w in fetch_tags),
    )

    raw_candidates = await build_candidates(fetch_tags, api_key, novelty, clients)

    logger.info("[pipeline:candidates] raw:%d", len(raw_candidates))

    # Sort for determinism before dedup (deduplicate_by_title keeps first winner)
    raw_candidates.sort(
        key=lambda c: f"{c.title}|||{c.artist}".lower()
        if hasattr(c, "title")
        else f"{c['title']}|||{c['artist']}".lower()
    )

    # Compute track-level tag scores against the weighted seed profile
    normalized_tag_weights = {}
    for tag, weight in tag_weights.items():
        normalized_tag_weights[normalize_tag(tag.lower())] = weight

    for c in raw_candidates:
        tags = c.tags if hasattr(c, "tags") else c["tags"]
        score = sum(
            normalized_tag_weights.get(normalize_tag(t.lower()), 0) for t in tags
        )
        if hasattr(c, "track_tag_score"):
            c.track_tag_score = score
        else:
            c["track_tag_score"] = score

    after_filter_seeds = filter_seeds(raw_candidates, seeds, exclude_seed_artists)
    logger.info(
        "[pipeline:dedup] after filter_seeds:%d (removed:%d)",
        len(after_filter_seeds),
        len(raw_candidates) - len(after_filter_seeds),
    )
    after_dedup_mbid = deduplicate_by_mbid(after_filter_seeds)
    logger.info(
        "[pipeline:dedup] after deduplicate_by_mbid:%d (removed:%d)",
        len(after_dedup_mbid),
        len(after_filter_seeds) - len(after_dedup_mbid),
    )
    candidates = deduplicate_by_title(after_dedup_mbid)
    logger.info(
        "[pipeline:dedup] after deduplicate_by_title:%d (removed:%d)",
        len(candidates),
        len(after_dedup_mbid) - len(candidates),
    )

    # Enrich all candidates with LF track tags. This serves two purposes:
    # 1) enables mood boosting - LB recording tags are genre-only (e.g. "shoegaze")
    #    and never contain mood words; without this step the mood multiplier never fires.
    # 2) Provides track-level signal for same-artist tie-breaking that the
    #    shared artist tag_weight_sum cannot resolve.
    # Tags are merged rather than replaced so LB genre labels are preserved for MMR.
    enriched_count = 0

    async def enrich_candidate(c):
        nonlocal enriched_count
        title = c.title if hasattr(c, "title") else c["title"]
        artist = c.artist if hasattr(c, "artist") else c["artist"]
        mbid = c.mbid if hasattr(c, "mbid") else c.get("mbid")
        try:
            lf_tags = await clients.fetch_track_tags_only(
                title, artist, api_key, mbid or None
            )
        except Exception:
            return
        if not lf_tags:
            return
        existing_tags = c.tags if hasattr(c, "tags") else c["tags"]
        existing_lower = {t.lower() for t in existing_tags}
        new_tags = [
            t.name if hasattr(t, "name") else t["name"]
            for t in lf_tags
            if (t.name if hasattr(t, "name") else t["name"]).lower()
            not in existing_lower
        ]
        if not new_tags:
            return
        if hasattr(c, "tags"):
            c.tags = existing_tags + new_tags
        else:
            c["tags"] = existing_tags + new_tags
        enriched_count += 1
        tags = c.tags if hasattr(c, "tags") else c["tags"]
        score = sum(
            normalized_tag_weights.get(normalize_tag(t.lower()), 0) for t in tags
        )
        if hasattr(c, "track_tag_score"):
            c.track_tag_score = score
        else:
            c["track_tag_score"] = score

    await asyncio.gather(*[enrich_candidate(c) for c in candidates])
    logger.info(
        "[pipeline:enrich] LF enrichment added tags to %d/%d candidates",
        enriched_count,
        len(candidates),
    )

    # For tracks with no listen count, fall back to artist-level popularity
    artist_mbids = [
        (c.artist_mbid if hasattr(c, "artist_mbid") else c["artist_mbid"])
        for c in candidates
        if (c.listen_count if hasattr(c, "listen_count") else c["listen_count"]) == 0
        and (c.artist_mbid if hasattr(c, "artist_mbid") else c["artist_mbid"])
    ]
    lb_artist_popularity = await clients.fetch_artist_popularity(
        list(set(artist_mbids))
    )
    for c in candidates:
        lc = c.listen_count if hasattr(c, "listen_count") else c["listen_count"]
        if lc == 0:
            ambid = c.artist_mbid if hasattr(c, "artist_mbid") else c["artist_mbid"]
            count = lb_artist_popularity.get(ambid)
            if count is not None:
                if hasattr(c, "artist_listen_count"):
                    c.artist_listen_count = count
                else:
                    c["artist_listen_count"] = count

    if mood and MOOD_TAGS.get(mood):
        mood_tag_set = set(MOOD_TAGS[mood])
        mood_boosted = 0
        for c in candidates:
            tags = c.tags if hasattr(c, "tags") else c["tags"]
            if any(t.lower() in mood_tag_set for t in tags):
                if hasattr(c, "tag_weight_sum"):
                    c.tag_weight_sum *= MOOD_MULTIPLIER
                else:
                    c["tag_weight_sum"] *= MOOD_MULTIPLIER
                mood_boosted += 1
        logger.info(
            '[pipeline:mood] mood="%s" boosted:%d/%d candidates (x%.1f)',
            mood,
            mood_boosted,
            len(candidates),
            MOOD_MULTIPLIER,
        )

    with_mbid = [
        c for c in candidates
        if (c.mbid if hasattr(c, "mbid") else c.get("mbid"))
    ]
    logger.info(
        "[pipeline:score] scoring %d candidates with mbid (dropped %d without mbid)",
        len(with_mbid),
        len(candidates) - len(with_mbid),
    )

    artist_track_count = {}
    artist_cap_dropped = []
    scored = score_and_sort(with_mbid, novelty)

    after_artist_cap = []
    for c in scored:
        artist = c.artist if hasattr(c, "artist") else c["artist"]
        key = artist.lower()
        count = artist_track_count.get(key, 0)
        if count >= MAX_TRACKS_PER_ARTIST:
            title = c.title if hasattr(c, "title") else c["title"]
            artist_cap_dropped.append(f'"{title}" by {artist}')
            continue
        artist_track_count[key] = count + 1
        after_artist_cap.append(c)

    if artist_cap_dropped:
        logger.info(
            "[pipeline:artistcap] dropped %d tracks (max %d/artist): %s",
            len(artist_cap_dropped),
            MAX_TRACKS_PER_ARTIST,
            ", ".join(artist_cap_dropped),
        )

    with_tag_match = [
        c for c in after_artist_cap
        if (c.track_tag_score if hasattr(c, "track_tag_score") else c["track_tag_score"]) > 0
    ]
    pre_mmr = (
        with_tag_match
        if len(with_tag_match) >= RECOMMENDATION_LIMIT
        else after_artist_cap
    )
    logger.info(
        "[pipeline:tagfloor] %d tracks with no seed tag match -- %s",
        len(after_artist_cap) - len(with_tag_match),
        "excluded" if pre_mmr is with_tag_match else "kept (pool too small to filter)",
    )
    logger.info(
        "[pipeline:mmr] selecting %d from %d scored candidates",
        RECOMMENDATION_LIMIT,
        len(pre_mmr),
    )
    top = mmr_select(pre_mmr, RECOMMENDATION_LIMIT)

    logger.info(
        "[candidates:final]\n%s",
        "\n".join(
            f'  [{i + 1}] "{c.title if hasattr(c, "title") else c["title"]}"'
            f' -- {c.artist if hasattr(c, "artist") else c["artist"]}'
            f'\n       mbid:{c.mbid if hasattr(c, "mbid") else c.get("mbid") or "none"}'
            f'\n       relevance:{c.relevance_score if hasattr(c, "relevance_score") else c["relevance_score"]:.3f}'
            f' novelty:{c.novelty_score if hasattr(c, "novelty_score") else c["novelty_score"]:.3f}'
            f' final:{c.final_score if hasattr(c, "final_score") else c["final_score"]:.3f}'
            for i, c in enumerate(top)
        ),
    )

    async def make_track(c):
        title = c.title if hasattr(c, "title") else c["title"]
        artist = c.artist if hasattr(c, "artist") else c["artist"]
        mbid = c.mbid if hasattr(c, "mbid") else c.get("mbid") or ""
        artist_mbid = c.artist_mbid if hasattr(c, "artist_mbid") else c["artist_mbid"]
        duration_ms = c.duration_ms if hasattr(c, "duration_ms") else c.get("duration_ms")
        rel_score = c.relevance_score if hasattr(c, "relevance_score") else c["relevance_score"]
        nov_score = c.novelty_score if hasattr(c, "novelty_score") else c["novelty_score"]
        streaming = await clients.get_streaming_links(artist, title)
        return Track(
            mbid=mbid,
            title=title,
            artist=artist,
            artist_mbid=artist_mbid,
            duration_ms=duration_ms,
            first_release_date=None,
            releases=[],
            streaming=streaming,
            relevance_score=rel_score,
            novelty_score=nov_score,
        )

    return list(await asyncio.gather(*[make_track(c) for c in top]))
