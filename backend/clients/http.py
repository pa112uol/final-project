import asyncio
import httpx

USER_AGENT = "NextTrack/1.0 (https://github.com/nexttrack)"

# One httpx.AsyncClient per named service, scoped to the running event loop.
# When the loop changes (a new asyncio.run() in tests) all clients are
# discarded and recreated so connections are never shared across loops.
_clients: dict[str, httpx.AsyncClient] = {}
_current_loop = None


def get_client(name: str, **kwargs) -> httpx.AsyncClient:
    global _clients, _current_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not _current_loop:
        _clients = {}
        _current_loop = loop
    if name not in _clients:
        kwargs.setdefault("headers", {"User-Agent": USER_AGENT})
        _clients[name] = httpx.AsyncClient(**kwargs)
    return _clients[name]
