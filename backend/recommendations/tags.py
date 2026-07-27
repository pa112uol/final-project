import re
import math
from .constants import LB_SOURCE_WEIGHT, TAG_COUNT_SCALE, DISTINCTIVE_TOP_N
from .types import LFTag
from .utils import get_field

# Last.fm user-collection tags that describe listening habits, not musical content
NOISE_TAGS = {
    "seen live",
    "favorites",
    "favourite",
    "love",
    "awesome",
    "good",
    "amazing",
    "beautiful",
    "cool",
    "songs i like",
    "favourite songs",
    "under 2000 listeners",
    "all",
    "music",
    "epic",
    "glorious",
}

# Genre roots, compound genre labels one level above sub-genre, and decade tags
# are excluded from candidate fetching - they pull in stylistically unrelated
# artists. Only sub-genre and scene tags (e.g. "britpop", "shoegaze") are used.
BROAD_FETCH_TAGS = {
    "rock",
    "pop",
    "pop rock",
    "alternative",
    "indie",
    "metal",
    "electronic",
    "electronica",
    "folk",
    "jazz",
    "classical",
    "punk",
    "dance",
    "hip hop",
    "r&b",
    "rap",
    "country",
    "soul",
    "blues",
    "reggae",
    "latin",
    "classic rock",
    "alternative rock",
    "general alternative rock",
    "indie rock",
    "indie pop",
    "60s",
    "70s",
    "80s",
    "90s",
    "00s",
    "2000s",
    "2010s",
    "2020s",
    "british",
}

# Nationality / geography tags describe where an artist is from, not how the
# music sounds. tag.getTopArtists on these returns a stylistically random
# cross-section of a whole country's output.
GEO_TAGS = {
    "american",
    "british",
    "english",
    "irish",
    "scottish",
    "welsh",
    "australian",
    "canadian",
    "swedish",
    "norwegian",
    "finnish",
    "german",
    "french",
    "italian",
    "spanish",
    "japanese",
    "korean",
    "brazilian",
    "usa",
    "uk",
    "california",
    "seattle",
    "london",
    "new york",
}

MOOD_TAGS = {
    "happy": ["happy", "upbeat", "feel good"],
    "sad": ["sad", "melancholic", "emotional"],
    "energetic": ["energetic", "hype", "workout"],
    "chill": ["chill", "relaxing", "mellow"],
    "angry": ["angry", "aggressive", "intense"],
    "melancholic": ["melancholic", "bittersweet", "nostalgic"],
    "romantic": ["romantic", "love"],
    "focus": ["focus", "study", "instrumental"],
}


# Normalize tags to a canonical form for merging and filtering
def normalize_tag(tag: str) -> str:
    return tag.replace("-", " ")


# Numeric tags ("-1001740215468") and specific year tags ("2019", "1990s")
# that slip past BROAD_FETCH_TAGS produce useless artist lists from
# tag.getTopArtists
def is_noise_tag(tag: str) -> bool:
    if re.fullmatch(r"-?\d+", tag):
        # numeric tags like -1001740215468
        return True
    if re.fullmatch(r"(19|20)\d{2}s?", tag):
        # full years or decades: 2019, 1990s, 2010s
        return True
    if re.fullmatch(r"\d{2}s", tag):
        # abbreviated decades: 70s, 80s, 90s
        return True
    if normalize_tag(tag).lower() in GEO_TAGS:
        # nationality/place tags: american, british, california
        return True
    return False


# Each seed's own tags ranked by that seed's counts. build_tag_weights pools
# every seed into one profile, which lets a single strongly-tagged seed own
# the top of the ranking; keeping the per-seed order lets the caller give
# every seed a guaranteed share of the fetch budget.
def rank_tags_per_seed(seed_tag_sets: list) -> list:
    return [
        [
            get_field(entry, "name")
            for entry in sorted(tags, key=lambda e: -get_field(e, "count", 0))
        ]
        for tags in seed_tag_sets
    ]


# Collapse a single source's tags to {normalized_name: share}, where share is
# relative to that source's own strongest tag. This is what makes the two
# sources comparable: it strips out whether the source counts in raw votes or
# in per-track percentages and leaves only "how strongly does this source
# associate this tag with this track".
def _normalized_source_counts(entries: list):
    totals = {}
    originals = {}
    for entry in entries:
        name = get_field(entry, "name")
        count = get_field(entry, "count", 0) or 0
        norm = normalize_tag(name)
        if norm in NOISE_TAGS:
            continue
        totals[norm] = totals.get(norm, 0) + count
        originals.setdefault(norm, name)
    max_count = max(totals.values(), default=0)
    if max_count <= 0:
        return {}, originals
    return {norm: c / max_count for norm, c in totals.items()}, originals


# Blend ListenBrainz and Last.fm tags additively, so a tag both sources agree
# on reinforces instead of one source's value being discarded.
def merge_tags(lb_tags: list, lf_tags: list) -> list:
    lb_counts, lb_originals = _normalized_source_counts(lb_tags)
    lf_counts, lf_originals = _normalized_source_counts(lf_tags)

    # A missing source hands its whole share to the other rather than shrinking
    # the profile. Otherwise a seed ListenBrainz has no data for would
    # contribute systematically weaker tags than its co-seeds to the pooled
    # multi-seed profile, purely because of upstream availability.
    lb_share = LB_SOURCE_WEIGHT
    lf_share = 1 - LB_SOURCE_WEIGHT
    if not lb_counts:
        lb_share, lf_share = 0.0, 1.0
    elif not lf_counts:
        lb_share, lf_share = 1.0, 0.0

    # Iterate in insertion order (LB first, then LF-only tags) rather than over
    # a set, so equal-weighted tags always tie-break the same way across runs.
    ordered_norms = list(lb_counts) + [
        norm for norm in lf_counts if norm not in lb_counts
    ]

    merged = []
    for norm in ordered_norms:
        blended = lb_share * lb_counts.get(norm, 0) + lf_share * lf_counts.get(
            norm, 0
        )
        if blended <= 0:
            continue
        original = lb_originals.get(norm) or lf_originals.get(norm)
        merged.append(LFTag(name=original, count=blended * TAG_COUNT_SCALE))
    return merged


# Compute tag weights for a set of seed tags, using TF-IDF style weighting
def build_tag_weights(seed_tag_sets: list) -> dict:
    total_seeds = max(len(seed_tag_sets), 1)
    tag_tf = {}
    tag_df = {}
    tag_original = {}

    for tags in seed_tag_sets:
        seen_in_seed = set()
        for entry in tags:
            name = get_field(entry, "name")
            count = get_field(entry, "count")
            norm = normalize_tag(name)
            tag_tf[norm] = tag_tf.get(norm, 0) + count
            if norm not in tag_original:
                tag_original[norm] = name
            if norm not in seen_in_seed:
                tag_df[norm] = tag_df.get(norm, 0) + 1
                seen_in_seed.add(norm)

    # Flipped from standard IDF: a tag shared by every seed is consensus, not
    # noise, so log(df/N) rewards it instead of log(N/df) suppressing it.
    weights = {}
    for norm, tf in tag_tf.items():
        df = tag_df.get(norm, 1)
        idf = 1 + math.log((df + 1) / (total_seeds + 1))
        weights[tag_original[norm]] = tf * idf

    return weights


# The tags that belong to one seed's top tags and to no other seed's. Tags
# every seed shares say nothing about which seed a track leans toward, so only
# the distinctive ones identify a track's seed. Used both to steer selection
# toward covering every seed and to measure whether it did
def distinctive_tags_per_seed(
    seed_tag_sets: list, top_n: int = DISTINCTIVE_TOP_N
) -> list:
    per_seed = [
        {
            normalize_tag(get_field(entry, "name").lower())
            for entry in sorted(tags, key=lambda e: -get_field(e, "count", 0))[
                :top_n
            ]
        }
        for tags in seed_tag_sets
    ]
    distinctive = []
    for index, own in enumerate(per_seed):
        others = (
            set().union(
                *(other for i, other in enumerate(per_seed) if i != index)
            )
            if len(per_seed) > 1
            else set()
        )
        distinctive.append(own - others)
    return distinctive


# Which seeds a track reflects, by its tags. A track can reflect several seeds
# at once that is a bridge result, not an error
def seeds_matched_by_track(track_tags: list, distinctive: list) -> set:
    tags = {normalize_tag(t.lower()) for t in track_tags}
    return {
        index for index, seed_tags in enumerate(distinctive) if tags & seed_tags
    }
