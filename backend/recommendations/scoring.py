import math
from .types import Candidate, ScoredCandidate
from .constants import (
    LISTEN_VS_USER_BLEND,
    REC_VS_ARTIST_BLEND,
    ARTIST_VS_TRACK_TAG_BLEND,
    MOOD_SCORE_WEIGHT,
)
from .utils import get_field


def median(values: list) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


# Obscurity from a listen count, normalized on a log scale against the max.
# Log scale is essential: listen counts are power-law distributed, so linear
# normalization lets one mega-popular track flatten everything else to ~1
def log_obscurity(count: int, log_max: float) -> float:
    if log_max <= 0:
        return 0
    return 1 - math.log1p(count) / log_max


def _compute_maxes(candidates: list) -> dict:
    maxes = {
        "relevance": 0.0,
        "track_tag_score": 0.0,
        "listen_count": 1,
        "user_count": 1,
        "artist_listen_count": 1,
    }
    for c in candidates:
        maxes["relevance"] = max(
            maxes["relevance"], get_field(c, "tag_weight_sum")
        )
        maxes["track_tag_score"] = max(
            maxes["track_tag_score"], get_field(c, "track_tag_score")
        )
        maxes["listen_count"] = max(
            maxes["listen_count"], get_field(c, "listen_count")
        )
        maxes["user_count"] = max(
            maxes["user_count"], get_field(c, "user_count")
        )
        maxes["artist_listen_count"] = max(
            maxes["artist_listen_count"], get_field(c, "artist_listen_count")
        )
    return maxes


# Blend listen count (scale) with user count (breadth) so repeat-play niche
# hits don't outscore genuinely popular tracks.
def _recording_obscurity(lc, uc, log_max_listen, log_max_user) -> float:
    listen_obsc = log_obscurity(lc, log_max_listen)
    user_obsc = log_obscurity(uc, log_max_user) if uc > 0 else listen_obsc
    return (
        LISTEN_VS_USER_BLEND * listen_obsc
        + (1 - LISTEN_VS_USER_BLEND) * user_obsc
    )


# First pass: obscurity for candidates with any popularity data. Recording
# count is the more specific signal, blended with artist-level obscurity as
# a fallback for tracks lacking their own listen data.
def _compute_obscurity_map(
    candidates: list, log_max_listen, log_max_user, log_max_artist
):
    obscurity_map = {}
    known = []
    for c in candidates:
        lc = get_field(c, "listen_count")
        uc = get_field(c, "user_count")
        alc = get_field(c, "artist_listen_count")
        has_rec = lc > 0
        has_art = alc > 0
        if not has_rec and not has_art:
            continue
        rec_obsc = (
            _recording_obscurity(lc, uc, log_max_listen, log_max_user)
            if has_rec
            else None
        )
        art_obsc = log_obscurity(alc, log_max_artist) if has_art else None
        if rec_obsc is not None and art_obsc is not None:
            o = (
                REC_VS_ARTIST_BLEND * rec_obsc
                + (1 - REC_VS_ARTIST_BLEND) * art_obsc
            )
        else:
            o = rec_obsc if rec_obsc is not None else art_obsc
        obscurity_map[id(c)] = o
        known.append(o)
    return obscurity_map, known


def _relevance_for_candidate(c, max_relevance, max_track_tag_score) -> float:
    tag_ws = get_field(c, "tag_weight_sum")
    tts = get_field(c, "track_tag_score")
    artist_norm = tag_ws / max_relevance if max_relevance > 0 else 0
    if max_track_tag_score > 0 and tts > 0:
        track_tag_norm = tts / max_track_tag_score
    else:
        # Penalize tracks with no tag match against seed profile
        track_tag_norm = artist_norm * 0.5
    return (
        ARTIST_VS_TRACK_TAG_BLEND * artist_norm
        + (1 - ARTIST_VS_TRACK_TAG_BLEND) * track_tag_norm
    )


# Mood adjusts the blended score rather than relevance itself. Folding it into
# tag_weight_sum (as the old multiplier did) made a track-level signal scale an
# artist-level genre score, corrupting relevance, and left mood with no effect
# whatsoever at novelty=1 where relevance is zero-weighted. Adding it here can
# push final_score slightly outside [0,1]; that is fine, since the value is
# only ever compared against other candidates' by the sort and by MMR.
# Exactly a no-op when no mood was requested: mood_score is 0.0 for every
# candidate and x + 0.0 == x.
def _with_mood(final_score: float, candidate) -> float:
    mood_score = get_field(candidate, "mood_score", 0.0) or 0.0
    return final_score + MOOD_SCORE_WEIGHT * mood_score


# Compute raw relevance and obscurity before normalizing so both can be
# min-max scaled to [0,1]. Without this relevance clusters near the top of
# its range while obscurity spans the full range, biasing novelty=0.5 toward relevance.
def _compute_raw_scores(
    candidates, obscurity_map, neutral, max_relevance, max_track_tag_score
):
    raw_scores = []
    for c in candidates:
        relevance = _relevance_for_candidate(
            c, max_relevance, max_track_tag_score
        )
        obs = obscurity_map.get(id(c), neutral)
        raw_scores.append((c, relevance, obs))
    return raw_scores


def _as_scored_candidate(
    c, final_score, relevance_norm, novelty_score
) -> ScoredCandidate:
    if isinstance(c, ScoredCandidate):
        c.final_score = final_score
        c.relevance_score = relevance_norm
        c.novelty_score = novelty_score
        return c
    return ScoredCandidate(
        title=get_field(c, "title"),
        artist=get_field(c, "artist"),
        artist_mbid=get_field(c, "artist_mbid"),
        mbid=get_field(c, "mbid"),
        duration_ms=get_field(c, "duration_ms"),
        tag_weight_sum=get_field(c, "tag_weight_sum"),
        track_tag_score=get_field(c, "track_tag_score"),
        listen_count=get_field(c, "listen_count"),
        user_count=get_field(c, "user_count"),
        artist_listen_count=get_field(c, "artist_listen_count"),
        tags=get_field(c, "tags"),
        mood_score=get_field(c, "mood_score", 0.0) or 0.0,
        final_score=final_score,
        relevance_score=relevance_norm,
        novelty_score=novelty_score,
    )


def score_and_sort(candidates: list, novelty: float) -> list:
    if not candidates:
        return []

    maxes = _compute_maxes(candidates)
    log_max_listen = math.log1p(maxes["listen_count"])
    log_max_user = math.log1p(maxes["user_count"])
    log_max_artist = math.log1p(maxes["artist_listen_count"])

    obscurity_map, known = _compute_obscurity_map(
        candidates, log_max_listen, log_max_user, log_max_artist
    )
    # Tracks with no popularity data get the median observed obscurity, not a
    # hardcoded 0.5, so they sit neutrally within the actual distribution.
    neutral = median(known) if known else 0.5

    raw_scores = _compute_raw_scores(
        candidates,
        obscurity_map,
        neutral,
        maxes["relevance"],
        maxes["track_tag_score"],
    )

    min_rel = min(r for _, r, _ in raw_scores)
    max_rel = max(r for _, r, _ in raw_scores)
    min_obs = min(o for _, _, o in raw_scores)
    max_obs = max(o for _, _, o in raw_scores)
    range_rel = max_rel - min_rel if max_rel != min_rel else 1
    range_obs = max_obs - min_obs if max_obs != min_obs else 1

    result = []
    for c, relevance, obs in raw_scores:
        relevance_norm = (relevance - min_rel) / range_rel
        popularity_obscurity = (obs - min_obs) / range_obs
        final_score = (
            1 - novelty
        ) * relevance_norm + novelty * popularity_obscurity
        final_score = _with_mood(final_score, c)
        result.append(_as_scored_candidate(c, final_score, relevance_norm, obs))

    result.sort(key=lambda x: x.final_score, reverse=True)
    return result
