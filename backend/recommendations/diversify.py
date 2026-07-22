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


def mmr_select(ranked: list, k: int) -> list:
    remaining = [
        {
            "c": c,
            "tokens": tokenize(get_field(c, "tags")),
            "artist": (get_field(c, "artist") or "").lower(),
        }
        for c in ranked
    ]
    selected = []

    while len(selected) < k and remaining:
        best_idx = _pick_best(remaining, selected)
        selected.append(remaining.pop(best_idx))

    return [item["c"] for item in selected]
