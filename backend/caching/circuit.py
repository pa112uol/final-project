# Circuit breaker shared by the sync and async cache implementations
# Implements the Circuit Breaker pattern as described by Fowler
# https://martinfowler.com/bliki/CircuitBreaker.html

import logging
import threading
import time

from .config import CIRCUIT_RETRY_S

logger = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(self, name: str, retry_after_s: float = CIRCUIT_RETRY_S):
        self._name = name
        self._retry_after_s = retry_after_s
        self._open_until = 0.0
        self._is_open = False
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def is_available(self) -> bool:
        return not self._is_open or time.monotonic() >= self._open_until

    # Returns True if the circuit is closed or the open period has expired, False
    # if the circuit is open and the open period has not yet expired
    def allows_request(self) -> bool:
        if not self._is_open:
            return True
        with self._lock:
            if not self._is_open:
                return True
            now = time.monotonic()
            if now < self._open_until:
                return False
            self._open_until = now + self._retry_after_s
            return True

    def record_success(self) -> None:
        with self._lock:
            was_open = self._is_open
            self._is_open = False
            self._open_until = 0.0
        if was_open:
            logger.warning(
                "[cache:%s] Redis recovered, cache re-enabled", self._name
            )

    # Opens the breaker. Logs at warning level only on the transition, because a
    # single request can touch the cache hundreds of times and one failure must
    # not produce hundreds of identical warnings
    def record_failure(self, exc: BaseException) -> None:
        with self._lock:
            was_open = self._is_open
            self._is_open = True
            self._open_until = time.monotonic() + self._retry_after_s
        if not was_open:
            logger.warning(
                "[cache:%s] Redis unavailable (%s: %s), serving uncached for %ss",
                self._name,
                type(exc).__name__,
                exc,
                self._retry_after_s,
            )
        else:
            logger.debug(
                "[cache:%s] Redis still unavailable: %s", self._name, exc
            )

    def reset(self) -> None:
        with self._lock:
            self._is_open = False
            self._open_until = 0.0
