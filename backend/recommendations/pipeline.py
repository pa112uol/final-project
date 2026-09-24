import asyncio
import logging
import math
import os
from .types import ScoredPool, Track, search_only_streaming_links
from .candidates import build_candidates
from .tags import (
    build_tag_weights,
    merge_tags,
    rank_tags_per_seed,
    distinctive_tags_per_seed,
    seeds_matched_by_track,
    normalize_for_match,
    is_noise_tag,
    BROAD_FETCH_TAGS,
)
from .mood import apply_mood_scores
from .dedup import filter_seeds, deduplicate_by_mbid, deduplicate_by_title
from .scoring import score_and_sort
from .diversify import mmr_select, mmr_select_balanced
from .constants import (
    RECOMMENDATION_LIMIT,
    TOP_TAGS_COUNT,
    MAX_TRACKS_PER_ARTIST,
    ENRICH_TOP_ARTISTS,
    ENRICH_TRACKS_PER_ARTIST,
    ENRICH_MODES,
    ENRICH_MODE_ALL,
    ENRICH_MODE_AUTO,
    ENRICH_MODE_FINAL,
    ENRICH_MODE_HYBRID,
    DEFAULT_ENRICH_MODE,
    POST_SELECTION_ENRICH_MODES,
    HIGH_NOVELTY_ENRICH_THRESHOLD,
    SELECTION_TOP_MATCH,
    MMR_LAMBDA,
)
from .utils import get_field, set_field, env_flag

logger = logging.getLogger(__name__)


# Select the final RECOMMENDATION_LIMIT tracks, optionally guaranteeing each
# seed a share of the slots when the feature is enabled and there is more than
# one seed
def select_final_tracks(
    pre_mmr: list,
    seed_tag_sets: list,
    limit: int,
    mmr_lambda: float = MMR_LAMBDA,
) -> list:
    if env_flag("RECS_SEED_BALANCED", True) and len(seed_tag_sets) > 1:
        distinctive = distinctive_tags_per_seed(seed_tag_sets)

        def seed_ids_of(candidate):
            return seeds_matched_by_track(
                get_field(candidate, "tags"), distinctive
            )

        logger.info(
            "[pipeline:mmr] seed-balanced selection, distinctive tag sizes:%s",
            [len(d) for d in distinctive],
        )
        return mmr_select_balanced(
            pre_mmr, limit, seed_ids_of, len(seed_tag_sets), mmr_lambda
        )
    return mmr_select(pre_mmr, limit, mmr_lambda)


# Log the tags associated with a seed
def _log_seed_tags(kind: str, title: str, tags: list) -> None:
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
def _log_dedup_stage(stage: str, before_count: int, after_count: int) -> None:
    logger.info(
        "[pipeline:dedup] after %s:%d (removed:%d)",
        stage,
        after_count,
        before_count - after_count,
    )


# Log the final selected candidates with their scores
def _log_final_candidates(top: list) -> None:
    logger.info(
        "[candidates:final]\n%s",
        "\n".join(
            f'  [{i + 1}] "{get_field(c, "title")}"'
            f' - {get_field(c, "artist")}'
            f'\n       mbid:{get_field(c, "mbid") or "none"}'
            f'\n       relevance:{get_field(c, "relevance_score"):.3f}'
            f' novelty:{get_field(c, "novelty_score"):.3f}'
            f' final:{get_field(c, "final_score"):.3f}'
            for i, c in enumerate(top)
        ),
    )


async def fetch_and_merge_seed_tags(seed, clients, api_key: str) -> list:
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


def _is_specific_tag(tag: str, seed_artist_names: set) -> bool:
    norm = normalize_for_match(tag)
    return (
        norm not in BROAD_FETCH_TAGS
        and norm not in seed_artist_names
        and not is_noise_tag(tag)
    )


# Interleave each seed's own top specific tags so every seed gets a share of
# the fetch budget. A global top-K over the pooled profile can be won outright
# by one seed: seeds usually agree only on broad tags ("rock"), which are
# filtered here, leaving single-seed tags whose IDF term is then a constant -
# so the pooled ranking degenerates into raw tag counts and a two-seed query
# silently becomes a one-seed query
def _round_robin_seed_tags(
    per_seed_tags: list, weight_of: dict, seed_artist_names: set
) -> tuple:
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
            norm = normalize_for_match(tag)
            if norm not in seen:
                seen.add(norm)
                chosen.append((tag, weight_of.get(norm, 0)))
        if len(chosen) >= TOP_TAGS_COUNT:
            break
    return chosen, seen


# Prefer specific tags for fetching. Fallback to broad ones only when fewer
# than 2 specific tags exist (e.g. a pure rock seed with no sub-genre)
def select_fetch_tags(
    sorted_tags: list, seed_artist_names: set, per_seed_tags: list | None = None
) -> list:
    specific_tags = [
        (tag, w)
        for tag, w in sorted_tags
        if _is_specific_tag(tag, seed_artist_names)
    ]

    if len(specific_tags) < 2:
        return [
            (tag, w)
            for tag, w in sorted_tags
            if normalize_for_match(tag) not in seed_artist_names
            and not is_noise_tag(tag)
        ][:TOP_TAGS_COUNT]

    if not per_seed_tags or len(per_seed_tags) < 2:
        return specific_tags[:TOP_TAGS_COUNT]

    weight_of = {normalize_for_match(tag): w for tag, w in sorted_tags}
    chosen, seen = _round_robin_seed_tags(
        per_seed_tags, weight_of, seed_artist_names
    )
    # Top up from the pooled ranking if the seeds had few specific tags
    for tag, w in specific_tags:
        if len(chosen) >= TOP_TAGS_COUNT:
            break
        norm = normalize_for_match(tag)
        if norm not in seen:
            seen.add(norm)
            chosen.append((tag, w))
    return chosen


# Cosine similarity between the candidate's binary tag vector and the weighted
# seed profile. Dividing by the vector length stops a candidate scoring highly
# for merely carrying more tags which matters because LF enrichment tags some
# candidates and not others. The seed profile's norm is omitted since it is
# constant across candidates, so it would scale every score alike without reranking
def compute_track_tag_score(tags: list, normalized_tag_weights: dict) -> float:
    if not tags:
        return 0.0
    matched = sum(
        normalized_tag_weights.get(normalize_for_match(t), 0) for t in tags
    )
    if not matched:
        return 0.0
    return matched / math.sqrt(len(tags))


# Compute track-level tag scores against the weighted seed profile
def score_candidates_by_seed_tags(
    candidates: list, normalized_tag_weights: dict
) -> None:
    for c in candidates:
        tags = get_field(c, "tags")
        score = compute_track_tag_score(tags, normalized_tag_weights)
        set_field(c, "track_tag_score", score)


# Deduplicate candidates by seed filtering, MBID, and title. Log the number of
# candidates removed at each stage for visibility into the pipeline's behaviour
def filter_and_deduplicate_candidates(
    raw_candidates: list, seeds: list, exclude_seed_artists: bool
) -> list:
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


# Picks the enrichment mode for a request. RECS_ENRICH_MODE always wins so a
# run can be pinned for testing. Otherwise auto reads novelty and mood. High
# novelty can defer tags only when no mood needs their evidence before ranking.
def enrich_mode(novelty: float | None = None, mood: str | None = None) -> str:
    configured = os.environ.get("RECS_ENRICH_MODE", DEFAULT_ENRICH_MODE)
    mode = configured.strip().lower()
    if mode not in ENRICH_MODES:
        mode = DEFAULT_ENRICH_MODE
    if mode != ENRICH_MODE_AUTO:
        return mode
    if (
        novelty is not None
        and novelty >= HIGH_NOVELTY_ENRICH_THRESHOLD
        and not mood
    ):
        return ENRICH_MODE_FINAL
    return ENRICH_MODE_HYBRID


# Returns the candidates to enrich before selection: every candidate in "all"
# mode, none in "final" mode, and for the capped modes the most listened tracks
# of the highest scoring artists
def select_enrichment_targets(
    candidates: list,
    novelty: float | None = None,
    mood: str | None = None,
) -> list:
    mode = enrich_mode(novelty, mood)
    if mode == ENRICH_MODE_ALL:
        return list(candidates)
    if mode == ENRICH_MODE_FINAL:
        return []

    by_artist: dict[str, list] = {}
    for candidate in candidates:
        by_artist.setdefault(get_field(candidate, "artist").lower(), []).append(
            candidate
        )

    # Every track of an artist carries the same tag_weight_sum, so the first
    # one is enough to rank the artist
    ranked_artists = sorted(
        by_artist.items(),
        key=lambda item: (-get_field(item[1][0], "tag_weight_sum"), item[0]),
    )[:ENRICH_TOP_ARTISTS]

    targets = []
    for _, artist_candidates in ranked_artists:
        artist_candidates.sort(
            key=lambda c: (
                -get_field(c, "listen_count"),
                get_field(c, "title").lower(),
            )
        )
        targets.extend(artist_candidates[:ENRICH_TRACKS_PER_ARTIST])
    return targets


async def enrich_candidate_with_lf_tags(
    candidate, clients, api_key: str, normalized_tag_weights: dict
) -> bool:
    title = get_field(candidate, "title")
    artist = get_field(candidate, "artist")
    mbid = get_field(candidate, "mbid")
    try:
        lf_tags = await clients.fetch_track_tags_only(
            title, artist, api_key, mbid or None
        )
    except Exception:
        return False
    # The call is spent even when no usable tags come back, so mark the
    # candidate before the early returns and stop a later pass paying twice
    set_field(candidate, "lf_enriched", True)
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


# Enrich all candidates with LF track tags. Candidates come from ListenBrainz,
# whose tag data is intermittent and thin for less popular recordings, and LF
# also adds track-level signal for the same-artist tie-breaking that a shared
# artist tag_weight_sum cannot resolve. The gap is coverage rather than mood,
# since LB recording tags do carry mood words like "mellow". Tags are merged
# rather than replaced so LB genre labels survive for MMR
async def enrich_candidates_with_lf_tags(
    candidates: list,
    clients,
    api_key: str,
    normalized_tag_weights: dict,
    novelty: float | None = None,
    mood: str | None = None,
) -> None:
    targets = select_enrichment_targets(candidates, novelty, mood)
    results = await asyncio.gather(
        *[
            enrich_candidate_with_lf_tags(
                c, clients, api_key, normalized_tag_weights
            )
            for c in targets
        ]
    )
    enriched_count = sum(1 for enriched in results if enriched)
    logger.info(
        "[pipeline:enrich] LF enrichment added tags to %d/%d candidates"
        " (%d of %d fetched)",
        enriched_count,
        len(candidates),
        len(targets),
        len(candidates),
    )


# Tops up the selected tracks with per-track tags. Only modes that skipped or
# capped the pre-selection pass have anything left to fetch, and already
# enriched tracks are skipped, so this costs at most one call per result
async def enrich_selected_tracks(
    selected: list,
    clients,
    api_key: str,
    normalized_tag_weights: dict,
    novelty: float | None = None,
    mood: str | None = None,
) -> None:
    mode = enrich_mode(novelty, mood)
    if mode not in POST_SELECTION_ENRICH_MODES:
        return
    pending = [c for c in selected if not get_field(c, "lf_enriched", False)]
    if not pending:
        return
    await asyncio.gather(
        *[
            enrich_candidate_with_lf_tags(
                c, clients, api_key, normalized_tag_weights
            )
            for c in pending
        ]
    )
    logger.info(
        "[pipeline:enrich] topped up %d/%d selected tracks (mode=%s)",
        len(pending),
        len(selected),
        mode,
    )


# For tracks with no listen count, fall back to artist-level popularity
async def apply_artist_popularity_fallback(candidates: list, clients) -> None:
    artist_mbids = [
        get_field(c, "artist_mbid")
        for c in candidates
        if get_field(c, "listen_count") == 0 and get_field(c, "artist_mbid")
    ]
    try:
        lb_artist_popularity = await clients.fetch_artist_popularity(
            list(set(artist_mbids))
        )
    except Exception as exc:
        # Every other stage degrades rather than failing the request, and this
        # one can too... without artist counts the affected candidates keep
        # artist_listen_count 0 and scoring gives them the median obscurity
        logger.warning(
            "[pipeline:popularity] fetch_artist_popularity failed: %s", exc
        )
        return
    for c in candidates:
        if get_field(c, "listen_count") == 0:
            count = lb_artist_popularity.get(get_field(c, "artist_mbid"))
            if count is not None:
                set_field(c, "artist_listen_count", count)


def apply_artist_cap(scored: list, max_per_artist: int) -> list:
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


def _with_tag_match(candidates: list) -> list:
    return [c for c in candidates if get_field(c, "track_tag_score") > 0]


# The floor only filters when enough tag-matched tracks remain to fill the list,
# otherwise it falls back to keeping unmatched tracks
def tag_floor_applies(candidates: list, limit: int) -> bool:
    return len(_with_tag_match(candidates)) >= limit


def apply_tag_floor(candidates: list, limit: int) -> list:
    with_tag_match = _with_tag_match(candidates)
    excluded = tag_floor_applies(candidates, limit)
    logger.info(
        "[pipeline:tagfloor] %d tracks with no seed tag match -- %s",
        len(candidates) - len(with_tag_match),
        "excluded" if excluded else "kept (pool too small to filter)",
    )
    return with_tag_match if excluded else candidates


# Builds the final Track for one selected candidate. Recording resolution is
# deferred to /api/recording/, so mbid/duration are used as-is and releases stay empty
async def build_track_from_candidate(candidate, clients):
    title = get_field(candidate, "title")
    artist = get_field(candidate, "artist")
    mbid = get_field(candidate, "mbid") or ""
    artist_mbid = get_field(candidate, "artist_mbid")
    duration_ms = get_field(candidate, "duration_ms")
    rel_score = get_field(candidate, "relevance_score")
    nov_score = get_field(candidate, "novelty_score")
    reason = get_field(candidate, "selection_reason", SELECTION_TOP_MATCH)
    tags = get_field(candidate, "tags", [])
    ranking_tags = get_field(candidate, "ranking_tags", None)

    # RECS_STREAMING_LINKS=0 drops the per-track iTunes and YouTube lookups,
    # used by the load harness to time the pipeline rather than its link fan-out
    if env_flag("RECS_STREAMING_LINKS", True):
        streaming = await clients.get_streaming_links(artist, title)
    else:
        streaming = search_only_streaming_links(artist, title)

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
        ranking_tags=ranking_tags if ranking_tags is not None else tags,
        selection_reason=reason,
    )


# Stages 1 to 4 of the pipeline: profile the seeds, retrieve and clean
# candidates, enrich them, then score. Returns None when the seeds have no tags
async def build_scored_pool(
    seeds: list,
    api_key: str,
    mood,
    novelty: float,
    clients,
    exclude_seed_artists: bool = True,
) -> ScoredPool | None:
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
        return None

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
        normalize_for_match(tag): weight for tag, weight in tag_weights.items()
    }
    score_candidates_by_seed_tags(raw_candidates, normalized_tag_weights)

    # Cleaning: filter out seed tracks/artists, collapse duplicate recordings
    candidates = filter_and_deduplicate_candidates(
        raw_candidates, seeds, exclude_seed_artists
    )

    # Stage 3: Enrich with track-level tags, then artist-level popularity
    await enrich_candidates_with_lf_tags(
        candidates,
        clients,
        api_key,
        normalized_tag_weights,
        novelty,
        mood,
    )
    await apply_artist_popularity_fallback(candidates, clients)
    # Mood is scored after enrichment, since mood tags usually arrive with
    # the Last.fm track tags rather than the ListenBrainz ones
    apply_mood_scores(candidates, mood)

    # Preserve the exact tag evidence used by scoring, mood and MMR. The
    # post-selection enrichment pass may add metadata tags, but it must not
    # rewrite the explanation of a decision that has already been made.
    for candidate in candidates:
        set_field(
            candidate,
            "ranking_tags",
            list(get_field(candidate, "tags", [])),
        )

    # Stage 4: Score by relevance/novelty
    with_mbid = [c for c in candidates if get_field(c, "mbid")]
    logger.info(
        "[pipeline:score] scoring %d candidates with mbid (dropped %d without mbid)",
        len(with_mbid),
        len(candidates) - len(with_mbid),
    )

    return ScoredPool(
        seed_tag_sets=seed_tag_sets,
        normalized_tag_weights=normalized_tag_weights,
        retrieved=candidates,
        scored=score_and_sort(with_mbid, novelty),
    )


# Stages 5 and 6: cap per artist, floor by tag match, then diversify via MMR.
# artist_cap None disables the cap and mmr_lambda 1.0 disables the diversity term
def select_from_pool(
    scored: list,
    seed_tag_sets: list,
    limit: int = RECOMMENDATION_LIMIT,
    artist_cap: int | None = MAX_TRACKS_PER_ARTIST,
    mmr_lambda: float = MMR_LAMBDA,
) -> list:
    capped = scored if artist_cap is None else apply_artist_cap(scored, artist_cap)
    pre_mmr = apply_tag_floor(capped, limit)
    logger.info(
        "[pipeline:mmr] selecting %d from %d scored candidates",
        limit,
        len(pre_mmr),
    )
    return select_final_tracks(pre_mmr, seed_tag_sets, limit, mmr_lambda)


async def run_pipeline(
    seeds: list,
    api_key: str,
    mood,
    novelty: float,
    clients,
    exclude_seed_artists: bool = True,
) -> list:
    pool = await build_scored_pool(
        seeds, api_key, mood, novelty, clients, exclude_seed_artists
    )
    if pool is None:
        return []

    top = select_from_pool(pool.scored, pool.seed_tag_sets)
    # Modes that skip or cap the pre-selection pass would otherwise return
    # tracks with only the sparse tags the source supplied, so top up the
    # winners before returning
    await enrich_selected_tracks(
        top,
        clients,
        api_key,
        pool.normalized_tag_weights,
        novelty,
        mood,
    )
    _log_final_candidates(top)

    return list(
        await asyncio.gather(
            *[build_track_from_candidate(c, clients) for c in top]
        )
    )
