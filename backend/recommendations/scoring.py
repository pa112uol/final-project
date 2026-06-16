import math
from .types import Candidate, ScoredCandidate
from .constants import (
    LISTEN_VS_USER_BLEND,
    REC_VS_ARTIST_BLEND,
    ARTIST_VS_TRACK_TAG_BLEND,
)


def median(values: list) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


# Obscurity from a listen count, normalized on a log scale against the max.
# Log scale is essential: listen counts are power-law distributed, so linear
# normalization lets one mega-popular track flatten everything else to ~1.
def log_obscurity(count: int, log_max: float) -> float:
    if log_max <= 0:
        return 0
    return 1 - math.log1p(count) / log_max


def score_and_sort(candidates: list, novelty: float) -> list:
    if not candidates:
        return []

    max_relevance = 0.0
    max_track_tag_score = 0.0
    max_listen_count = 1
    max_user_count = 1
    max_artist_listen_count = 1

    for c in candidates:
        tag_ws = c.tag_weight_sum if isinstance(c, Candidate) else c["tag_weight_sum"]
        tts = c.track_tag_score if isinstance(c, Candidate) else c["track_tag_score"]
        lc = c.listen_count if isinstance(c, Candidate) else c["listen_count"]
        uc = c.user_count if isinstance(c, Candidate) else c["user_count"]
        alc = c.artist_listen_count if isinstance(c, Candidate) else c["artist_listen_count"]
        if tag_ws > max_relevance:
            max_relevance = tag_ws
        if tts > max_track_tag_score:
            max_track_tag_score = tts
        if lc > max_listen_count:
            max_listen_count = lc
        if uc > max_user_count:
            max_user_count = uc
        if alc > max_artist_listen_count:
            max_artist_listen_count = alc

    log_max_listen = math.log1p(max_listen_count)
    log_max_user = math.log1p(max_user_count)
    log_max_artist = math.log1p(max_artist_listen_count)

    # First pass: obscurity for candidates with any popularity data. Recording
    # count is the more specific signal. Blend listen count (scale) with user
    # count (breadth) so repeat-play niche hits don't outscore genuinely popular tracks.
    obscurity_map = {}
    known = []
    for c in candidates:
        lc = c.listen_count if isinstance(c, Candidate) else c["listen_count"]
        uc = c.user_count if isinstance(c, Candidate) else c["user_count"]
        alc = c.artist_listen_count if isinstance(c, Candidate) else c["artist_listen_count"]
        has_rec = lc > 0
        has_art = alc > 0
        if not has_rec and not has_art:
            continue
        rec_obsc = None
        if has_rec:
            listen_obsc = log_obscurity(lc, log_max_listen)
            user_obsc = log_obscurity(uc, log_max_user) if uc > 0 else listen_obsc
            rec_obsc = (
                LISTEN_VS_USER_BLEND * listen_obsc
                + (1 - LISTEN_VS_USER_BLEND) * user_obsc
            )
        art_obsc = log_obscurity(alc, log_max_artist) if has_art else None
        if rec_obsc is not None and art_obsc is not None:
            o = REC_VS_ARTIST_BLEND * rec_obsc + (1 - REC_VS_ARTIST_BLEND) * art_obsc
        else:
            o = rec_obsc if rec_obsc is not None else art_obsc
        obscurity_map[id(c)] = o
        known.append(o)

    # Tracks with no popularity data get the median observed obscurity, not a
    # hardcoded 0.5, so they sit neutrally within the actual distribution.
    neutral = median(known) if known else 0.5

    # Compute raw relevance and obscurity before normalizing so we can min-max
    # scale both to [0,1]. Without this relevance clusters near the top of its
    # range while obscurity spans the full range, making novelty=0.5 biased toward relevance.
    raw_scores = []
    for c in candidates:
        tag_ws = c.tag_weight_sum if isinstance(c, Candidate) else c["tag_weight_sum"]
        tts = c.track_tag_score if isinstance(c, Candidate) else c["track_tag_score"]
        artist_norm = tag_ws / max_relevance if max_relevance > 0 else 0
        if max_track_tag_score > 0 and tts > 0:
            track_tag_norm = tts / max_track_tag_score
        else:
            # Penalize tracks with no tag match against seed profile
            track_tag_norm = artist_norm * 0.5
        relevance = (
            ARTIST_VS_TRACK_TAG_BLEND * artist_norm
            + (1 - ARTIST_VS_TRACK_TAG_BLEND) * track_tag_norm
        )
        obs = obscurity_map.get(id(c), neutral)
        raw_scores.append((c, relevance, obs))

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
        final_score = (1 - novelty) * relevance_norm + novelty * popularity_obscurity

        if isinstance(c, ScoredCandidate):
            sc = c
            sc.final_score = final_score
            sc.relevance_score = relevance_norm
            sc.novelty_score = popularity_obscurity
        else:
            sc = ScoredCandidate(
                title=c.title if isinstance(c, Candidate) else c["title"],
                artist=c.artist if isinstance(c, Candidate) else c["artist"],
                artist_mbid=c.artist_mbid if isinstance(c, Candidate) else c["artist_mbid"],
                mbid=c.mbid if isinstance(c, Candidate) else c["mbid"],
                duration_ms=c.duration_ms if isinstance(c, Candidate) else c.get("duration_ms"),
                tag_weight_sum=c.tag_weight_sum if isinstance(c, Candidate) else c["tag_weight_sum"],
                track_tag_score=c.track_tag_score if isinstance(c, Candidate) else c["track_tag_score"],
                listen_count=c.listen_count if isinstance(c, Candidate) else c["listen_count"],
                user_count=c.user_count if isinstance(c, Candidate) else c["user_count"],
                artist_listen_count=c.artist_listen_count if isinstance(c, Candidate) else c["artist_listen_count"],
                tags=c.tags if isinstance(c, Candidate) else c["tags"],
                final_score=final_score,
                relevance_score=relevance_norm,
                novelty_score=popularity_obscurity,
            )
        result.append(sc)

    result.sort(key=lambda x: x.final_score, reverse=True)
    return result
