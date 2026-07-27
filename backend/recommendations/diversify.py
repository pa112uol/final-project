import math
from .constants import MMR_LAMBDA
from .utils import get_field


def tokenize(tags: list) -> set:
    tokens = set()
    for tag in tags:
        for word in tag.lower().split():
            if word:
                tokens.add(word)
    return tokens


def jaccard_sets(a: set, b: set) -> float:
    if not a or not b:
        return 0
    intersection = len(a & b)
    return intersection / (len(a) + len(b) - intersection)


# Two tracks by the same artist are maximally redundant regardless of how
# their tag strings happen to overlap, so artist identity short-circuits the
# tag comparison. Without this a second track by an already-selected artist
# pays only a partial Jaccard penalty and can still outrank a fresh artist.
def _pair_similarity(item, other) -> float:
    if item["artist"] and item["artist"] == other["artist"]:
        return 1.0
    return jaccard_sets(item["tokens"], other["tokens"])


def _max_similarity_to_selected(item: dict, selected: list) -> float:
    if not selected:
        return 0
    return max(_pair_similarity(item, other) for other in selected)


def _mmr_score(item: dict, selected: list) -> float:
    max_sim = _max_similarity_to_selected(item, selected)
    final_score = get_field(item["c"], "final_score")
    return MMR_LAMBDA * final_score - (1 - MMR_LAMBDA) * max_sim


def _pick_best(remaining: list, selected: list) -> int:
    best_idx = 0
    best_score = float("-inf")
    for i, item in enumerate(remaining):
        score = _mmr_score(item, selected)
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def _prepare_items(ranked: list, seed_ids_of=None) -> list:
    return [
        {
            "c": c,
            "tokens": tokenize(get_field(c, "tags")),
            "artist": (get_field(c, "artist") or "").lower(),
            "seeds": seed_ids_of(c) if seed_ids_of else set(),
        }
        for c in ranked
    ]


# Pick the candidate with the best MMR score, then repeat until k are selected.
# MMR balances relevance or final_score against diversity or max similarity
# to already-selected candidates
def mmr_select(ranked: list, k: int) -> list:
    remaining = _prepare_items(ranked)
    selected = []

    while len(selected) < k and remaining:
        best_idx = _pick_best(remaining, selected)
        selected.append(remaining.pop(best_idx))

    return [item["c"] for item in selected]


# The seed each unmet slot must be filled from: the one furthest below its quota
# that still has a matching candidate left. Returns None once every seed has met
# quota or none of the deficit seeds have candidates remaining
def _needy_seed(remaining: list, counts: list, target: int) -> int | None:
    deficit_seeds = sorted(
        (s for s in range(len(counts)) if counts[s] < target),
        key=lambda s: counts[s],
    )
    for seed in deficit_seeds:
        if any(seed in item["seeds"] for item in remaining):
            return seed
    return None


# MMR selection that guarantees each seed a share of the slots. Plain MMR ranks
# on one pooled score, so a cross-genre pair's dominant seed out-scores the
# other and can take every slot, the measured failure where a two seed query
# returns nothing from one seed. Here each step fills the most under quota seed
# from its own candidates, still by MMR score so relevance and diversity decide
# within a seed, then falls back to global MMR once quotas are met
def mmr_select_balanced(
    ranked: list, k: int, seed_ids_of, seed_count: int
) -> list:
    if seed_count <= 1:
        return mmr_select(ranked, k)

    remaining = _prepare_items(ranked, seed_ids_of)
    selected = []
    target = math.ceil(k / seed_count)
    counts = [0] * seed_count

    while len(selected) < k and remaining:
        seed = _needy_seed(remaining, counts, target)
        if seed is None:
            pool = remaining
        else:
            pool = [item for item in remaining if seed in item["seeds"]]
        best = pool[_pick_best(pool, selected)]
        # Identity, not equality: two candidates could compare equal as
        # dataclasses, and remove() would drop the wrong one.
        remaining = [item for item in remaining if item is not best]
        selected.append(best)
        for matched in best["seeds"]:
            if matched < seed_count:
                counts[matched] += 1

    return [item["c"] for item in selected]
