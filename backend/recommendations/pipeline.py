import asyncio
import logging
import math
from .types import Track, Release
from .candidates import build_candidates
from .tags import (
    build_tag_weights,
    merge_tags,
    rank_tags_per_seed,
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


def _is_specific_tag(tag, seed_artist_names):
    norm = normalize_tag(tag).lower()
    return (
        norm not in BROAD_FETCH_TAGS
        and norm not in seed_artist_names
        and not is_noise_tag(tag)
    )


# Interleave each seed's own top specific tags so every seed gets a share of
# the fetch budget. A global top-K over the pooled profile can be won outright
# by one seed: seeds usually agree only on broad tags ("rock"), which are
# filtered here, leaving single-seed tags whose IDF term is then a constant --
# so the pooled ranking degenerates into raw tag counts and a two-seed query
# silently becomes a one-seed query.
def _round_robin_seed_tags(per_seed_tags, weight_of, seed_artist_names):
    queues = [
        [t for t in tags if _is_specific_tag(t, seed_artist_names)]
        for tags in per_seed_tags
    ]
    chosen = []
    seen = set()
    for depth in range(max((len(q) for q in queues), default=0)):
        for queue in queues:
            if depth >= len(queue) or len(chosen) >= TOP_TAGS_COUNT:
                continue
            tag = queue[depth]
            norm = normalize_tag(tag).lower()
            if norm not in seen:
                seen.add(norm)
                chosen.append((tag, weight_of.get(norm, 0)))
        if len(chosen) >= TOP_TAGS_COUNT:
            break
    return chosen, seen


# Prefer specific tags for fetching. Fallback to broad ones only when fewer
# than 2 specific tags exist (e.g. a pure rock seed with no sub-genre)
def select_fetch_tags(sorted_tags, seed_artist_names, per_seed_tags=None):
    specific_tags = [
        (tag, w)
        for tag, w in sorted_tags
        if _is_specific_tag(tag, seed_artist_names)
    ]

    if len(specific_tags) < 2:
        return [
            (tag, w)
            for tag, w in sorted_tags
            if normalize_tag(tag).lower() not in seed_artist_names
            and not is_noise_tag(tag)
        ][:TOP_TAGS_COUNT]

    if not per_seed_tags or len(per_seed_tags) < 2:
        return specific_tags[:TOP_TAGS_COUNT]

    weight_of = {
        normalize_tag(tag).lower(): w for tag, w in sorted_tags
    }
    chosen, seen = _round_robin_seed_tags(
        per_seed_tags, weight_of, seed_artist_names
    )
    # Top up from the pooled ranking if the seeds had few specific tags
    for tag, w in specific_tags:
        if len(chosen) >= TOP_TAGS_COUNT:
            break
        if normalize_tag(tag).lower() not in seen:
            seen.add(normalize_tag(tag).lower())
            chosen.append((tag, w))
    return chosen


# Cosine similarity between the candidate's (binary) tag vector and the
# weighted seed profile. A raw weight sum rewards a candidate for merely
# carrying more tags -- and LF enrichment adds tags to some candidates and not
# others -- so dividing by the vector length removes that bias. The seed
# profile's norm is constant across candidates and so is omitted; it would
# scale every score identically without changing the ranking.
def compute_track_tag_score(tags, normalized_tag_weights):
    if not tags:
        return 0.0
    matched = sum(
        normalized_tag_weights.get(normalize_tag(t.lower()), 0) for t in tags
    )
    if not matched:
        return 0.0
    return matched / math.sqrt(len(tags))


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
# 1) It fills coverage gaps: candidates come from ListenBrainz, whose tag data
# is intermittent and thin for less popular recordings. (Note LB tags are not
# genre-only -- the recording scope does carry mood words like "mellow" and
# "bittersweet" -- so this is about coverage, not about mood specifically.)
# 2) It provides track-level signal for same-artist tie-breaking that the shared
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
    streaming, resolved = await asyncio.gather(
        clients.get_streaming_links(artist, title),
        clients.resolve_recording_mbid(mbid, title, artist),
    )
    mbid = resolved["mbid"]
    if duration_ms is None:
        duration_ms = resolved["duration_ms"]
    releases = (
        [
            Release(
                mbid=resolved["release_mbid"],
                title=resolved["album"],
                date=resolved["release_date"],
            )
        ]
        if resolved["album"]
        else []
    )
    return Track(
        mbid=mbid,
        title=title,
        artist=artist,
        artist_mbid=artist_mbid,
        duration_ms=duration_ms,
        first_release_date=resolved["release_date"],
        releases=releases,
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
    # Name breaks weight ties so the fetch set is stable across runs
    sorted_tags = sorted(tag_weights.items(), key=lambda x: (-x[1], x[0]))

    if not sorted_tags:
        return []

    # Exclude tags that match a seed artist name, e.g. "queen" for a Queen seed
    # would make fetch_tag_artists return mostly Queen members and collaborators
    seed_artist_names = {get_field(s, "artist").lower() for s in seeds}
    fetch_tags = select_fetch_tags(
        sorted_tags, seed_artist_names, rank_tags_per_seed(seed_tag_sets)
    )
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
