import re
import math
from .constants import LB_TAG_SCALE
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
    return False


# Merge ListenBrainz and Last.fm tags, weighting LB tags higher than LF tags
def merge_tags(lb_tags: list, lf_tags: list) -> list:
    merged = {}
    for entry in lb_tags:
        name = get_field(entry, "name")
        count = get_field(entry, "count")
        norm = normalize_tag(name)
        if norm not in NOISE_TAGS:
            if norm in merged:
                merged[norm]["count"] += count * LB_TAG_SCALE
            else:
                merged[norm] = {"count": count * LB_TAG_SCALE, "original": name}
    # Last.fm supplements with mood/vibe tags absent from LB; if a tag is
    # already present from LB, keep the boosted LB weight
    for entry in lf_tags:
        name = get_field(entry, "name")
        count = get_field(entry, "count")
        norm = normalize_tag(name)
        if norm not in NOISE_TAGS and norm not in merged:
            merged[norm] = {"count": count, "original": name}
    return [
        LFTag(name=v["original"], count=v["count"]) for v in merged.values()
    ]


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
