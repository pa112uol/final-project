# Redis key construction.

import hashlib

from .config import KEY_PREFIX

MAX_INLINE_KEY_LENGTH = 120
_HASH_LENGTH = 16
PART_SEPARATOR = "|"
SEQUENCE_SEPARATOR = ","
_ESCAPE = "\\"
_ESCAPED = (_ESCAPE, PART_SEPARATOR, SEQUENCE_SEPARATOR)


# Normalises one key component. Case and surrounding whitespace are stripped so
# "The Beatles" and "the beatles " share an entry
def _normalise(part: object) -> str:
    if part is None:
        return "~"
    if isinstance(part, bool):
        return "1" if part else "0"
    if isinstance(part, (list, tuple)):
        return SEQUENCE_SEPARATOR.join(_normalise(p) for p in part)
    text = str(part).strip().lower()
    for char in _ESCAPED:
        text = text.replace(char, _ESCAPE + char)
    return text


# Builds a stable, collision-resistant key from a namespace and the
# arguments that identify a cached value
def build_key(namespace: str, *parts: object) -> str:
    if not namespace:
        raise ValueError("namespace is required")
    body = PART_SEPARATOR.join(_normalise(p) for p in parts)
    if len(body) > MAX_INLINE_KEY_LENGTH:
        body = hashlib.sha256(body.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
    return f"{KEY_PREFIX}{namespace}:{body}"
