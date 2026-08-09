"""Framework-free settings object, replacing backend/backend/settings.py.
Reads the same three dotenv files in the same order so env behaviour is
unchanged by the migration.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from caching.config import parse_bool

# app/ sits directly under backend/, matching the old BASE_DIR
BASE_DIR = Path(__file__).resolve().parent.parent

# backend/.env, then backend/.env.local, then the repo root .env.local,
# each later file overriding the earlier ones
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local")
load_dotenv(BASE_DIR.parent / ".env.local")

DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]


# Parses an int environment variable, falling back to a default on anything
# missing or unparseable
def _parse_int(value: str | None, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    debug: bool = False
    lastfm_api_key: str = ""
    youtube_api_key: str = ""
    redis_url: str = ""
    cache_enabled: bool = True
    max_seed_tracks: int = 5
    cors_origins: list[str] = field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))


# Reads settings from the environment. Cached, so every request-time
# get_settings() call is a dict lookup rather than a fresh os.environ parse
@lru_cache
def get_settings() -> Settings:
    return Settings(
        debug=os.environ.get("DEBUG", "False") == "True",
        lastfm_api_key=os.environ.get("LASTFM_API_KEY", ""),
        youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""),
        redis_url=os.environ.get("REDIS_URL", ""),
        cache_enabled=parse_bool(os.environ.get("CACHE_ENABLED"), default=True),
        max_seed_tracks=_parse_int(os.environ.get("MAX_SEED_TRACKS"), default=5),
        cors_origins=list(DEFAULT_CORS_ORIGINS),
    )
