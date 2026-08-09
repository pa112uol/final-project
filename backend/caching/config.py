import os

KEY_PREFIX = "nexttrack:v1:"

SECOND = 1
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# How long a failed or empty upstream result is remembered before retrying
NEGATIVE_TTL_S = 5 * MINUTE

# TTLs are set by how fast the underlying data actually moves, not by uniform
# convention: MBIDs never change, chart data drifts weekly, listen counts drift
# continuously
TTL_ARTIST_MBID = 30 * DAY
TTL_RECORDING_MBID = 30 * DAY
TTL_TAG_ARTISTS = 7 * DAY
TTL_TRACK_TAGS = 7 * DAY
TTL_RECORDING_TAGS = 7 * DAY
TTL_TOP_RECORDINGS = 3 * DAY
TTL_ARTIST_POPULARITY = 6 * HOUR

# Streaming links get the longest non-MBID TTL deliberately: the YouTube Data
# API charges 100 quota units per search against a 10,000/day default, which
# caps the whole app at ~100 uncached recommendation runs per day. The
# (artist, title) to videoId mapping never changes, so this is the single most
# valuable thing in the cache
TTL_STREAMING_LINKS = 14 * DAY

# Cover art: a found URL is permanent data, a miss is usually a transient
# MusicBrainz/Cover Art Archive failure
TTL_COVERART = 30 * DAY

TTL_RANDOM_POOL = 60 * SECOND
TTL_RANDOM_POOL_STALE = 10 * MINUTE

# Upper bound on how long one worker may hold the refresh lock
RANDOM_POOL_LOCK_TTL_S = 45 * SECOND

# Once Redis has failed, every subsequent call would otherwise pay a full
# connection timeout, making an api slower than an uncached one
CIRCUIT_RETRY_S = 30 * SECOND

# Deliberately short, waiting longer on it than the work it saves defeats the purpose
CONNECT_TIMEOUT_S = 2
SOCKET_TIMEOUT_S = 2


# Reads a setting from the environment. app/config.py loads the project's
# dotenv files before anything else runs, so os.environ is the single
# source of truth here
def _get_setting(name: str, default: str) -> str:
    return os.environ.get(name, default)


_TRUE_VALUES = ("1", "true", "yes", "on")
_FALSE_VALUES = ("0", "false", "no", "off")


def parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return default


def redis_url() -> str:
    return _get_setting("REDIS_URL", "").strip()


# The cache is on only when explicitly enabled and pointed at a server
def cache_enabled() -> bool:
    enabled = parse_bool(_get_setting("CACHE_ENABLED", "True"), default=True)
    return enabled and bool(redis_url())
