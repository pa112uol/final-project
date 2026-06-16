import asyncio
import logging
from .http import get_client

# MusicBrainz requires a meaningful User-Agent: App/Version (contact)
# See https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
MB_BASE = "https://musicbrainz.org/ws/2"
MB_MIN_INTERVAL_S = 1.5

logger = logging.getLogger(__name__)

# asyncio.Lock + a serial queue ensures MB requests are fully serialized.
# Each request waits for the previous fetch + cooldown to finish before firing.
_mb_lock = asyncio.Lock()
_last_request_time = 0.0


async def mb_fetch(url: str):
    global _last_request_time
    async with _mb_lock:
        now = asyncio.get_running_loop().time()
        elapsed = now - _last_request_time
        if elapsed < MB_MIN_INTERVAL_S:
            await asyncio.sleep(MB_MIN_INTERVAL_S - elapsed)
        res = await get_client("musicbrainz", timeout=10).get(url)
        _last_request_time = asyncio.get_running_loop().time()
        return res


async def resolve_artist_mbid(name: str) -> str:
    clean_name = name.replace('"', "")
    query = f'artist:"{clean_name}"'
    try:
        res = await mb_fetch(
            f"{MB_BASE}/artist?query={query}&limit=1&fmt=json"
        )
        if not res.is_success:
            return ""
        data = res.json()
        artists = data.get("artists") or []
        if not artists:
            return ""
        top = artists[0]
        if top.get("score", 0) < 85:
            return ""
        return top.get("id", "")
    except Exception:
        return ""
