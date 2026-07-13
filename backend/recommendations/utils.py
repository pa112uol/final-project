def get_field(obj, key, default=None):
    if hasattr(obj, key):
        return getattr(obj, key)
    return obj.get(key, default) if isinstance(obj, dict) else default


def set_field(obj, key, value):
    if hasattr(obj, key):
        setattr(obj, key, value)
    else:
        obj[key] = value
