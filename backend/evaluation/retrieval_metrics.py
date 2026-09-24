from __future__ import annotations

import math
import random
import re
import unicodedata
from dataclasses import dataclass
from statistics import fmean

from recommendations.dedup import normalize_title
from recommendations.tags import (
    distinctive_tags_per_seed,
    seeds_matched_by_track,
)
from recommendations.utils import get_field
from evaluation.playlist_catalogue import PlaylistTrack, artist_identity
from tests.eval.test_eval import intralist_diversity

BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260921
CONFIDENCE_LEVEL = 0.95


def fold_text(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").casefold()))


# Same title collapsing the pipeline's deduplication uses, so "Song (Remastered)"
# and "Song" count as one track. Seed resolution uses it, so it stays as frozen
def title_key(artist: str, title: str) -> tuple[str, str]:
    return fold_text(artist), fold_text(normalize_title(title or ""))


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )


# Relevance folding on top of fold_text. Accents go, so Beyonce matches Beyonce
# with an acute accent, and "&" reads as "and"
def fold_name(text: str) -> str:
    return fold_text(re.sub(r"\s*&\s*", " and ", strip_accents(text)))


# Sources disagree on a leading article, as in The Weeknd and Weeknd
def fold_artist_name(name: str) -> str:
    return re.sub(r"^the ", "", fold_name(name))


def relevance_key(artist: str, title: str) -> tuple[str, str]:
    return fold_artist_name(artist), fold_name(normalize_title(title or ""))


# Maps candidates onto held-out tracks and artists. Recording and artist MBIDs
# match first. Normalised names are the fallback because Last.fm MBIDs are often stale
@dataclass(frozen=True)
class RelevanceSet:
    track_by_mbid: dict[str, int]
    track_by_title: dict[tuple[str, str], int]
    artist_by_mbid: dict[str, int]
    artist_by_name: dict[str, int]
    track_count: int
    artist_count: int

    def track_id(self, candidate) -> int | None:
        mbid = get_field(candidate, "mbid", "") or ""
        if mbid and mbid in self.track_by_mbid:
            return self.track_by_mbid[mbid]
        key = relevance_key(
            get_field(candidate, "artist"), get_field(candidate, "title")
        )
        return self.track_by_title.get(key)

    def artist_id(self, candidate) -> int | None:
        artist_mbid = get_field(candidate, "artist_mbid", "") or ""
        if artist_mbid and artist_mbid in self.artist_by_mbid:
            return self.artist_by_mbid[artist_mbid]
        return self.artist_by_name.get(
            fold_artist_name(get_field(candidate, "artist"))
        )


def build_relevance(held_out: tuple[PlaylistTrack, ...]) -> RelevanceSet:
    track_by_mbid: dict[str, int] = {}
    track_by_title: dict[tuple[str, str], int] = {}
    artist_index: dict[frozenset[str], int] = {}
    artist_by_mbid: dict[str, int] = {}
    artist_by_name: dict[str, int] = {}
    for index, track in enumerate(held_out):
        if track.recording_mbid:
            track_by_mbid.setdefault(track.recording_mbid, index)
        track_by_title.setdefault(
            relevance_key(track.artist, track.title), index
        )
        artist = artist_index.setdefault(
            artist_identity(track), len(artist_index)
        )
        for mbid in track.artist_mbids:
            artist_by_mbid.setdefault(mbid, artist)
        artist_by_name.setdefault(fold_artist_name(track.artist), artist)
    return RelevanceSet(
        track_by_mbid=track_by_mbid,
        track_by_title=track_by_title,
        artist_by_mbid=artist_by_mbid,
        artist_by_name=artist_by_name,
        track_count=len(held_out),
        artist_count=len(artist_index),
    )


def matched_ids(candidates: list, id_of) -> set[int]:
    return {match for c in candidates if (match := id_of(c)) is not None}


def recall(found: set[int], total: int) -> float:
    return len(found) / total if total else 0.0


@dataclass(frozen=True)
class RankScores:
    precision: float
    recall: float | None
    ndcg: float | None


def dcg(gains: list[float]) -> float:
    return sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))


# Precision counts over every case, so it measures retrieval and ranking together.
# Recall and nDCG are None when nothing relevant was rankable, so they measure ranking only
def rank_scores(
    selected: list, rankable_ids: set[int], id_of, k: int
) -> RankScores:
    counted: set[int] = set()
    gains = []
    for candidate in selected[:k]:
        match = id_of(candidate)
        hit = (
            match is not None and match in rankable_ids and match not in counted
        )
        if hit:
            counted.add(match)
        gains.append(1.0 if hit else 0.0)
    precision = len(counted) / k
    if not rankable_ids:
        return RankScores(precision, None, None)
    ideal = [1.0] * min(k, len(rankable_ids))
    return RankScores(
        precision=precision,
        recall=len(counted) / len(rankable_ids),
        ndcg=dcg(gains) / dcg(ideal),
    )


def candidate_artist_key(candidate) -> str:
    return get_field(candidate, "artist_mbid", "") or fold_text(
        get_field(candidate, "artist")
    )


@dataclass(frozen=True)
class ArtistConcentration:
    unique_artists: int
    max_artist_share: float


def artist_concentration(selected: list) -> ArtistConcentration:
    counts: dict[str, int] = {}
    for candidate in selected:
        key = candidate_artist_key(candidate)
        counts[key] = counts.get(key, 0) + 1
    share = max(counts.values()) / len(selected) if selected else 0.0
    return ArtistConcentration(len(counts), share)


# Tracks per seed under the distinctive-tag rule the balanced selector uses
def seed_counts(selected: list, seed_tag_sets: list) -> list[int]:
    distinctive = distinctive_tags_per_seed(seed_tag_sets)
    counts = [0] * len(seed_tag_sets)
    for candidate in selected:
        for seed in seeds_matched_by_track(
            get_field(candidate, "tags"), distinctive
        ):
            counts[seed] += 1
    return counts


@dataclass(frozen=True)
class SeedBalance:
    coverage: float
    balance: float
    quota_shortfall: bool


# Coverage is the share of seeds with a track. Balance is the smallest seed
# count over the largest. Shortfall means some seed missed its ceil(k/n) quota
def seed_balance(counts: list[int], k: int) -> SeedBalance | None:
    if len(counts) < 2:
        return None
    covered = sum(1 for count in counts if count > 0)
    largest = max(counts)
    quota = math.ceil(k / len(counts))
    return SeedBalance(
        coverage=covered / len(counts),
        balance=min(counts) / largest if largest else 0.0,
        quota_shortfall=any(count < quota for count in counts),
    )


def mean_field(selected: list, name: str) -> float:
    return fmean(get_field(c, name) for c in selected) if selected else 0.0


def list_diversity(selected: list) -> float:
    return float(intralist_diversity(selected))


def mean_defined(values: list[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    return fmean(defined) if defined else None


@dataclass(frozen=True)
class PairedDifference:
    pairs: int
    mean: float
    low: float
    high: float

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0 or self.high < 0


# Percentile bootstrap over cases for the mean of paired differences. Cases
# where either side is undefined are dropped, so the pairs always match
def paired_difference(
    treatment: list[float | None],
    baseline: list[float | None],
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> PairedDifference | None:
    if len(treatment) != len(baseline):
        raise ValueError("paired lists must have the same length")
    diffs = [
        after - before
        for after, before in zip(treatment, baseline)
        if after is not None and before is not None
    ]
    if not diffs:
        return None
    rng = random.Random(seed)
    means = sorted(
        fmean(rng.choices(diffs, k=len(diffs))) for _ in range(samples)
    )
    tail = (1 - CONFIDENCE_LEVEL) / 2
    return PairedDifference(
        pairs=len(diffs),
        mean=fmean(diffs),
        low=means[int(tail * (samples - 1))],
        high=means[int((1 - tail) * (samples - 1))],
    )
