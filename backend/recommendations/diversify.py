from .types import ScoredCandidate
from .constants import MMR_LAMBDA


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


def mmr_select(ranked: list, k: int) -> list:
    remaining = [
        {
            "c": c,
            "tokens": tokenize(
                c.tags if isinstance(c, ScoredCandidate) else c["tags"]
            ),
        }
        for c in ranked
    ]
    selected = []
    selected_tokens = []

    while len(selected) < k and remaining:
        best_idx = 0
        best_score = float("-inf")
        for i, item in enumerate(remaining):
            c = item["c"]
            tokens = item["tokens"]
            final_score = (
                c.final_score if isinstance(c, ScoredCandidate) else c["final_score"]
            )
            if selected_tokens:
                max_sim = max(jaccard_sets(tokens, st) for st in selected_tokens)
            else:
                max_sim = 0
            score = MMR_LAMBDA * final_score - (1 - MMR_LAMBDA) * max_sim
            if score > best_score:
                best_score = score
                best_idx = i

        selected.append(remaining[best_idx]["c"])
        selected_tokens.append(remaining[best_idx]["tokens"])
        remaining.pop(best_idx)

    return selected
