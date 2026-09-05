import os


def get_field(obj, key, default=None):
    if hasattr(obj, key):
        return getattr(obj, key)
    return obj.get(key, default) if isinstance(obj, dict) else default


def set_field(obj, key, value):
    if hasattr(obj, key):
        setattr(obj, key, value)
    else:
        obj[key] = value


# Reads a boolean feature flag from an environment variable so every toggle
# in the pipeline accepts the same set of truthy strings
def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes")
