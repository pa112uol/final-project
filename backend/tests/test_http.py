import asyncio
from unittest.mock import AsyncMock

import clients.http as client_http


def _clear_client_state() -> None:
    client_http._clients = {}
    client_http._current_loop = None


async def test_close_clients_closes_clients_owned_by_the_running_loop():
    client = AsyncMock()
    client_http._clients = {"service": client}
    client_http._current_loop = asyncio.get_running_loop()

    try:
        await client_http.close_clients()
        client.aclose.assert_awaited_once_with()
        assert client_http._clients == {}
        assert client_http._current_loop is None
    finally:
        _clear_client_state()


async def test_close_clients_discards_clients_owned_by_a_closed_loop():
    client = AsyncMock()
    old_loop = asyncio.new_event_loop()
    old_loop.close()
    client_http._clients = {"service": client}
    client_http._current_loop = old_loop

    try:
        await client_http.close_clients()
        client.aclose.assert_not_awaited()
        assert client_http._clients == {}
        assert client_http._current_loop is None
    finally:
        _clear_client_state()
