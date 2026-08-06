# Shared behaviour between the sync and async cache implementations

import logging

from .circuit import CircuitBreaker
from .config import cache_enabled
from .serialization import SerializationError, dumps, loads

logger = logging.getLogger(__name__)


class BaseCache:
    def __init__(self, connect, enabled=None, name: str = "cache"):
        self._connect = connect
        self._enabled_fn = enabled if enabled is not None else cache_enabled
        self._breaker = CircuitBreaker(name)
        self._name = name

    # The cache is usable only when configured and not currently circuit-open.
    # Checked before every operation so a mid-request Redis outage stops costing
    # connection timeouts immediately
    def _available(self) -> bool:
        return bool(self._enabled_fn()) and self._breaker.allows_request()

    def _on_success(self) -> None:
        self._breaker.record_success()

    def _on_failure(self, exc: BaseException) -> None:
        self._breaker.record_failure(exc)

    # Encodes a value for storage, returning None when it cannot be represented
    def _encode(self, value: object) -> str | None:
        try:
            return dumps(value)
        except SerializationError:
            logger.exception(
                "[cache:%s] refusing to store unencodable value", self._name
            )
            return None

    @staticmethod
    def _decode(raw) -> object | None:
        return loads(raw)

    @property
    def is_healthy(self) -> bool:
        return bool(self._enabled_fn()) and self._breaker.is_available

    def reset_breaker(self) -> None:
        self._breaker.reset()
