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


def _max_similarity_to_selected(tokens: set, selected_tokens: list) -> float:
    if not selected_tokens:
        return 0
    return max(jaccard_sets(tokens, st) for st in selected_tokens)


def _mmr_score(final_score: float, tokens: set, selected_tokens: list) -> float:
    max_sim = _max_similarity_to_selected(tokens, selected_tokens)
    return MMR_LAMBDA * final_score - (1 - MMR_LAMBDA) * max_sim


def _pick_best(remaining: list, selected_tokens: list) -> int:
    best_idx = 0
    best_score = float("-inf")
    for i, item in enumerate(remaining):
        final_score = get_field(item["c"], "final_score")
        score = _mmr_score(final_score, item["tokens"], selected_tokens)
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def mmr_select(ranked: list, k: int) -> list:
    remaining = [
        {"c": c, "tokens": tokenize(get_field(c, "tags"))}
        for c in ranked
    ]
    selected = []
    selected_tokens = []

    while len(selected) < k and remaining:
        best_idx = _pick_best(remaining, selected_tokens)
        selected.append(remaining[best_idx]["c"])
        selected_tokens.append(remaining[best_idx]["tokens"])
        remaining.pop(best_idx)

    return selected
