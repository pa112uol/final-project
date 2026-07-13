import asyncio
import logging
from .types import Track
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
from .utils import get_field, set_field

logger = logging.getLogger(__name__)


# Log the tags associated with a seed
def _log_seed_tags(kind, title, tags):
    logger.info(
        "%s for %s: %s",
        kind,
        title,
        ", ".join(
            f"{get_field(t, 'name')}({get_field(t, 'count')})" for t in tags
        )
        or "(none)",
    )


# Log the number of candidates remaining after a deduplication stage
def _log_dedup_stage(stage, before_count, after_count):
    logger.info(
        "[pipeline:dedup] after %s:%d (removed:%d)",
        stage,
        after_count,
        before_count - after_count,
    )


# Log the final selected candidates with their scores
def _log_final_candidates(top):
    logger.info(
        "[candidates:final]\n%s",
        "\n".join(
            f'  [{i + 1}] "{get_field(c, "title")}"'
            f' -- {get_field(c, "artist")}'
            f'\n       mbid:{get_field(c, "mbid") or "none"}'
            f'\n       relevance:{get_field(c, "relevance_score"):.3f}'
            f' novelty:{get_field(c, "novelty_score"):.3f}'
            f' final:{get_field(c, "final_score"):.3f}'
            for i, c in enumerate(top)
        ),
    )


async def fetch_and_merge_seed_tags(seed, clients, api_key):
    mbid = get_field(seed, "mbid")
    title = get_field(seed, "title")
    artist = get_field(seed, "artist")
    lb_task = (
        clients.fetch_recording_tags(mbid)
        if mbid
        else asyncio.sleep(0, result=[])
    )
    lf_task = clients.fetch_track_tags(title, artist, api_key, mbid or None)
    lb_tags, lf_tags = await asyncio.gather(lb_task, lf_task)
    _log_seed_tags("lf_tags", title, lf_tags)
    _log_seed_tags("lb_tags", title, lb_tags)
    return merge_tags(lb_tags, lf_tags)


# Prefer specific tags for fetching. Fallback to broad ones only when fewer
# than 2 specific tags exist (e.g. a pure rock seed with no sub-genre)
def select_fetch_tags(sorted_tags, seed_artist_names):
    specific_tags = [
        (tag, w)
        for tag, w in sorted_tags
        if (
            normalize_tag(tag) not in BROAD_FETCH_TAGS
            and tag not in seed_artist_names
            and not is_noise_tag(tag)
        )
    ][:TOP_TAGS_COUNT]

    if len(specific_tags) >= 2:
        return specific_tags

    return [
        (tag, w)
        for tag, w in sorted_tags
        if tag not in seed_artist_names and not is_noise_tag(tag)
    ][:TOP_TAGS_COUNT]


def compute_track_tag_score(tags, normalized_tag_weights):
    return sum(
        normalized_tag_weights.get(normalize_tag(t.lower()), 0) for t in tags
    )


# Compute track-level tag scores against the weighted seed profile
def score_candidates_by_seed_tags(candidates, normalized_tag_weights):
    for c in candidates:
        tags = get_field(c, "tags")
        score = compute_track_tag_score(tags, normalized_tag_weights)
        set_field(c, "track_tag_score", score)


def filter_and_deduplicate_candidates(
    raw_candidates, seeds, exclude_seed_artists
):
    after_filter_seeds = filter_seeds(
        raw_candidates, seeds, exclude_seed_artists
    )
    _log_dedup_stage(
        "filter_seeds", len(raw_candidates), len(after_filter_seeds)
    )

    after_dedup_mbid = deduplicate_by_mbid(after_filter_seeds)
    _log_dedup_stage(
        "deduplicate_by_mbid", len(after_filter_seeds), len(after_dedup_mbid)
    )

    candidates = deduplicate_by_title(after_dedup_mbid)
    _log_dedup_stage(
        "deduplicate_by_title", len(after_dedup_mbid), len(candidates)
    )
    return candidates


async def enrich_candidate_with_lf_tags(
    candidate, clients, api_key, normalized_tag_weights
):
    title = get_field(candidate, "title")
    artist = get_field(candidate, "artist")
    mbid = get_field(candidate, "mbid")
    try:
        lf_tags = await clients.fetch_track_tags_only(
            title, artist, api_key, mbid or None
        )
    except Exception:
        return False
    if not lf_tags:
        return False

    existing_tags = get_field(candidate, "tags")
    existing_lower = {t.lower() for t in existing_tags}
    new_tags = [
        get_field(t, "name")
        for t in lf_tags
        if get_field(t, "name").lower() not in existing_lower
    ]
    if not new_tags:
        return False

    merged_tags = existing_tags + new_tags
    set_field(candidate, "tags", merged_tags)
    score = compute_track_tag_score(merged_tags, normalized_tag_weights)
    set_field(candidate, "track_tag_score", score)
    return True


# Enrich all candidates with LF track tags.
# 1) It enables mood boosting - LB recording tags are genre-only (e.g. "shoegaze")
# and never contain mood words; without this step the mood multiplier never fires
# 2)It provides track-level signal for same-artist tie-breaking that the shared
# artist tag_weight_sum cannot resolve
# Tags are merged rather than replaced so LB genre labels are preserved for MMR.
async def enrich_candidates_with_lf_tags(
    candidates, clients, api_key, normalized_tag_weights
):
    results = await asyncio.gather(
        *[
            enrich_candidate_with_lf_tags(
                c, clients, api_key, normalized_tag_weights
            )
            for c in candidates
        ]
    )
    enriched_count = sum(1 for enriched in results if enriched)
    logger.info(
        "[pipeline:enrich] LF enrichment added tags to %d/%d candidates",
        enriched_count,
        len(candidates),
    )


# For tracks with no listen count, fall back to artist-level popularity
async def apply_artist_popularity_fallback(candidates, clients):
    artist_mbids = [
        get_field(c, "artist_mbid")
        for c in candidates
        if get_field(c, "listen_count") == 0 and get_field(c, "artist_mbid")
    ]
    lb_artist_popularity = await clients.fetch_artist_popularity(
        list(set(artist_mbids))
    )
    for c in candidates:
        if get_field(c, "listen_count") == 0:
            count = lb_artist_popularity.get(get_field(c, "artist_mbid"))
            if count is not None:
                set_field(c, "artist_listen_count", count)


def apply_mood_boost(candidates, mood):
    if not (mood and MOOD_TAGS.get(mood)):
        return
    mood_tag_set = set(MOOD_TAGS[mood])
    boosted = 0
    for c in candidates:
        tags = get_field(c, "tags")
        if any(t.lower() in mood_tag_set for t in tags):
            set_field(
                c,
                "tag_weight_sum",
                get_field(c, "tag_weight_sum") * MOOD_MULTIPLIER,
            )
            boosted += 1
    logger.info(
        '[pipeline:mood] mood="%s" boosted:%d/%d candidates (x%.1f)',
        mood,
        boosted,
        len(candidates),
        MOOD_MULTIPLIER,
    )


def apply_artist_cap(scored, max_per_artist):
    artist_track_count = {}
    dropped = []
    kept = []
    for c in scored:
        artist = get_field(c, "artist")
        key = artist.lower()
        count = artist_track_count.get(key, 0)
        if count >= max_per_artist:
            dropped.append(f'"{get_field(c, "title")}" by {artist}')
            continue
        artist_track_count[key] = count + 1
        kept.append(c)
    if dropped:
        logger.info(
            "[pipeline:artistcap] dropped %d tracks (max %d/artist): %s",
            len(dropped),
            max_per_artist,
            ", ".join(dropped),
        )
    return kept


def apply_tag_floor(candidates, limit):
    with_tag_match = [
        c for c in candidates if get_field(c, "track_tag_score") > 0
    ]
    excluded = len(with_tag_match) >= limit
    logger.info(
        "[pipeline:tagfloor] %d tracks with no seed tag match -- %s",
        len(candidates) - len(with_tag_match),
        "excluded" if excluded else "kept (pool too small to filter)",
    )
    return with_tag_match if excluded else candidates


async def build_track_from_candidate(candidate, clients):
    title = get_field(candidate, "title")
    artist = get_field(candidate, "artist")
    mbid = get_field(candidate, "mbid") or ""
    artist_mbid = get_field(candidate, "artist_mbid")
    duration_ms = get_field(candidate, "duration_ms")
    rel_score = get_field(candidate, "relevance_score")
    nov_score = get_field(candidate, "novelty_score")
    tags = get_field(candidate, "tags", [])
    streaming, mbid = await asyncio.gather(
        clients.get_streaming_links(artist, title),
        clients.resolve_final_mbid(mbid, title, artist),
    )
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
        tags=tags,
    )


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
            f'"{get_field(s, "title")}" by {get_field(s, "artist")}'
            for s in seeds
        ),
    )

    # Stage 1: Profile seeds into a weighted tag preference vector
    seed_tag_sets = await asyncio.gather(
        *[fetch_and_merge_seed_tags(seed, clients, api_key) for seed in seeds]
    )
    tag_weights = build_tag_weights(seed_tag_sets)
    sorted_tags = sorted(tag_weights.items(), key=lambda x: -x[1])

    if not sorted_tags:
        return []

    # Exclude tags that match a seed artist name, e.g. "queen" for a Queen seed
    # would make fetch_tag_artists return mostly Queen members and collaborators
    seed_artist_names = {get_field(s, "artist").lower() for s in seeds}
    fetch_tags = select_fetch_tags(sorted_tags, seed_artist_names)
    logger.info(
        "[tags] fetch tags: %s",
        ", ".join(f"{t}({w:.0f})" for t, w in fetch_tags),
    )

    # Stage 2: Expand tags into candidate tracks via tag, artist, recordings
    raw_candidates = await build_candidates(
        fetch_tags, api_key, novelty, clients
    )
    logger.info("[pipeline:candidates] raw:%d", len(raw_candidates))

    # Sort for determinism before dedup (deduplicate_by_title keeps first winner)
    raw_candidates.sort(
        key=lambda c: f"{get_field(c, 'title')}|||{get_field(c, 'artist')}".lower()
    )

    normalized_tag_weights = {
        normalize_tag(tag.lower()): weight
        for tag, weight in tag_weights.items()
    }
    score_candidates_by_seed_tags(raw_candidates, normalized_tag_weights)

    # Stage 3: Filter out seed tracks/artists and collapse duplicate recordings
    candidates = filter_and_deduplicate_candidates(
        raw_candidates, seeds, exclude_seed_artists
    )

    # Stage 4: Enrich with track-level tags, then fall back to artist-level
    # popularity for tracks ListenBrainz has no listen count for, and boost
    # candidates matching the requested mood
    await enrich_candidates_with_lf_tags(
        candidates, clients, api_key, normalized_tag_weights
    )
    await apply_artist_popularity_fallback(candidates, clients)
    apply_mood_boost(candidates, mood)

    # Stage 5: Score by relevance/novelty, cap per-artist, floor by tag
    # match then diversify the final selection via MMR
    with_mbid = [c for c in candidates if get_field(c, "mbid")]
    logger.info(
        "[pipeline:score] scoring %d candidates with mbid (dropped %d without mbid)",
        len(with_mbid),
        len(candidates) - len(with_mbid),
    )

    scored = score_and_sort(with_mbid, novelty)
    after_artist_cap = apply_artist_cap(scored, MAX_TRACKS_PER_ARTIST)
    pre_mmr = apply_tag_floor(after_artist_cap, RECOMMENDATION_LIMIT)

    logger.info(
        "[pipeline:mmr] selecting %d from %d scored candidates",
        RECOMMENDATION_LIMIT,
        len(pre_mmr),
    )
    top = mmr_select(pre_mmr, RECOMMENDATION_LIMIT)
    _log_final_candidates(top)

    return list(
        await asyncio.gather(
            *[build_track_from_candidate(c, clients) for c in top]
        )
    )
