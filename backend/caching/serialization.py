# JSON encoding for cached values

import json
from dataclasses import asdict, is_dataclass


class SerializationError(ValueError):
    pass


# Encodes a value for storage. Dataclasses become plain dicts first, so they
# survive the write/read cycle as data
def dumps(value: object) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise SerializationError(f"value is not JSON-encodable: {exc}") from exc


# Decodes a stored value
def loads(raw: str | bytes | None) -> object | None:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
