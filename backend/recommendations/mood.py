import logging

from .constants import MOOD_CONFLICT_PENALTY
from .tags import MOOD_TAGS, normalize_for_match
from .utils import get_field, set_field

logger = logging.getLogger(__name__)

# Tags listeners actually apply that imply a mood, with how strongly each does.
# The MOOD_TAGS entries stay the canonical vocabulary and always count 1.0;
# everything here is weaker evidence, so a pool where every track is merely
# "downtempo" does not score as strongly as one tagged "chill" outright.
# Without this table the matcher is blind to the tags that dominate real pools:
# "chillout" alone carries 55 of 91 candidates on a Massive Attack seed while
# the literal tag "chill" carries 5.
MOOD_RELATED: dict[str, dict[str, float]] = {
    "happy": {
        "feelgood": 0.9,
        "uplifting": 0.8,
        "joyful": 0.8,
        "cheerful": 0.8,
        "fun": 0.6,
        "sunny": 0.6,
    },
    "sad": {
        "melancholy": 0.9,
        "sadcore": 0.9,
        "heartbreak": 0.8,
        "depressing": 0.8,
        "somber": 0.7,
        "sombre": 0.7,
        "wistful": 0.6,
        "lonely": 0.6,
    },
    "energetic": {
        "high energy": 0.9,
        "upbeat": 0.8,
        "driving": 0.7,
        "banger": 0.7,
        "anthemic": 0.6,
        "party": 0.6,
    },
    "chill": {
        "chillout": 1.0,
        "chilled": 1.0,
        "relax": 0.9,
        "laid back": 0.8,
        "calm": 0.7,
        "downtempo": 0.7,
        "lounge": 0.6,
        "smooth": 0.5,
    },
    "angry": {
        "rage": 0.9,
        "abrasive": 0.8,
        "brutal": 0.8,
        "hardcore": 0.6,
        "heavy": 0.5,
    },
    "melancholic": {
        "melancholy": 1.0,
        "wistful": 0.8,
        "longing": 0.7,
        "sad": 0.7,
        "autumnal": 0.6,
    },
    "romantic": {
        "love songs": 1.0,
        "lovesong": 1.0,
        "sensual": 0.8,
        "intimate": 0.7,
        "sexy": 0.6,
    },
    "focus": {
        "ambient": 0.7,
        "background": 0.7,
        "minimal": 0.6,
        "post rock": 0.5,
    },
}

# Moods that argue against each other. A chill request should not silently keep
# an "aggressive" track at full score just because nothing demotes it. Only the
# canonical MOOD_TAGS terms of the opposing mood count, so a weak associate
# ("heavy" on a metal track) cannot torpedo a candidate on its own.
MOOD_CONFLICTS: dict[str, tuple[str, ...]] = {
    "happy": ("sad", "angry", "melancholic"),
    "sad": ("happy", "energetic"),
    "energetic": ("chill", "focus"),
    "chill": ("energetic", "angry"),
    "angry": ("chill", "happy", "romantic"),
    "melancholic": ("happy", "energetic"),
    "romantic": ("angry",),
    "focus": ("energetic", "angry"),
}


def _build_vocabulary(mood: str) -> dict[str, float]:
    vocabulary = {normalize_for_match(t): 1.0 for t in MOOD_TAGS.get(mood, ())}
    for tag, weight in MOOD_RELATED.get(mood, {}).items():
        # Canonical terms win: a related entry never downgrades a MOOD_TAG
        vocabulary.setdefault(normalize_for_match(tag), weight)
    return vocabulary


def _build_conflict_vocabulary(mood: str) -> dict[str, float]:
    conflicting = {}
    for opposing in MOOD_CONFLICTS.get(mood, ()):
        for tag in MOOD_TAGS.get(opposing, ()):
            conflicting[normalize_for_match(tag)] = 1.0
    # A tag that also signals the requested mood is not evidence against it
    # ("sad" opposes "happy" but is itself part of the melancholic vocabulary)
    for tag in _build_vocabulary(mood):
        conflicting.pop(tag, None)
    return conflicting


# Static vocabularies, built once. MOOD_TAGS and MOOD_RELATED never change at
# runtime, so rebuilding them per candidate would be pure waste.
MOOD_VOCABULARY: dict[str, dict[str, float]] = {
    mood: _build_vocabulary(mood) for mood in MOOD_TAGS
}
MOOD_CONFLICT_VOCABULARY: dict[str, dict[str, float]] = {
    mood: _build_conflict_vocabulary(mood) for mood in MOOD_TAGS
}


def is_known_mood(mood) -> bool:
    return bool(mood) and mood in MOOD_VOCABULARY


# How strongly a track's tags express a mood, in [-1, 1]. Graded rather than
# binary so a track tagged "chill" outranks one merely tagged "downtempo";
# negative when the track carries a contradicting mood's tags instead.
def mood_match_score(tags, mood) -> float:
    if not is_known_mood(mood) or not tags:
        return 0.0
    vocabulary = MOOD_VOCABULARY[mood]
    conflicting = MOOD_CONFLICT_VOCABULARY[mood]
    best_match = 0.0
    best_conflict = 0.0
    for tag in tags:
        normalized = normalize_for_match(tag)
        best_match = max(best_match, vocabulary.get(normalized, 0.0))
        best_conflict = max(best_conflict, conflicting.get(normalized, 0.0))
    score = best_match - MOOD_CONFLICT_PENALTY * best_conflict
    return max(-1.0, min(1.0, score))


def _log_coverage(mood: str, matched: int, opposed: int, total: int) -> None:
    if not total:
        return
    # A pool that cannot express the mood yields a response indistinguishable
    # from an unmoodied one, so say it out loud rather than returning silently.
    # Demoting a few opposing tracks is not the same as finding matching ones.
    if not matched:
        logger.warning(
            '[pipeline:mood] mood="%s" matched none of %d candidates '
            "(%d opposed) -- results will barely differ from an "
            "unfiltered request",
            mood,
            total,
            opposed,
        )
        return
    # Near-total coverage is equally worth flagging: a term applied at the same
    # strength to every candidate is a constant offset and cannot reorder
    # anything. It means the seed's whole neighbourhood already fits the mood
    if matched == total:
        logger.info(
            '[pipeline:mood] mood="%s" matched all %d candidates -- '
            "the seed's neighbourhood already fits, so ranking is unchanged",
            mood,
            total,
        )
        return
    logger.info(
        '[pipeline:mood] mood="%s" matched:%d opposed:%d of %d candidates',
        mood,
        matched,
        opposed,
        total,
    )


# Score every candidate for the requested mood, writing mood_score in place.
# Returns without touching a single candidate when no mood is requested, which
# is what keeps an unmoodied pipeline run bit-identical: every candidate keeps
# mood_score 0.0 and the scoring stage's mood term drops out.
def apply_mood_scores(candidates: list, mood) -> None:
    if not is_known_mood(mood):
        return
    matched = 0
    opposed = 0
    for candidate in candidates:
        score = mood_match_score(get_field(candidate, "tags"), mood)
        set_field(candidate, "mood_score", score)
        if score > 0:
            matched += 1
        elif score < 0:
            opposed += 1
    _log_coverage(mood, matched, opposed, len(candidates))
