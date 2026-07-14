"""Thread-safe, process-local TTL cache for external source data."""

from __future__ import annotations

import logging
import math
from copy import deepcopy
from dataclasses import dataclass
from threading import Event, RLock
from time import monotonic, perf_counter
from typing import Any, Callable, Hashable

from core.observability import elapsed_ms, log_event


logger = logging.getLogger(__name__)


class CacheCopyError(RuntimeError):
    """Raised for followers when a value cannot be copied safely."""


@dataclass(frozen=True)
class CacheLoadResult:
    value: Any
    cache_status: str


@dataclass
class _Entry:
    value: Any
    expires_at: float


@dataclass
class _Flight:
    event: Event
    service: str
    global_generation: int
    service_generation: int
    key_generation: int
    value: Any = None
    error: BaseException | None = None


class SourceCacheService:
    """Small TTL cache with per-key single-flight and defensive copies."""

    def __init__(self, *, clock: Callable[[], float] | None = None):
        self._clock = clock or monotonic
        self._entries: dict[Hashable, _Entry] = {}
        self._inflight: dict[Hashable, _Flight] = {}
        self._lock = RLock()
        self._global_generation = 0
        self._service_generations: dict[str, int] = {}
        self._key_generations: dict[Hashable, int] = {}

    def get_or_load(
        self,
        *,
        key: Hashable,
        ttl_seconds: float,
        loader: Callable[[], Any],
        is_cacheable: Callable[[Any], bool],
        service: str,
        dataset: str,
    ) -> CacheLoadResult:
        started_at = self._safe_started_at()
        now = self._safe_clock()
        if now is None or not self._valid_ttl(ttl_seconds):
            self._safe_event(
                "source_cache_lookup_end",
                result="error",
                started_at=started_at,
                service=service,
                dataset=dataset,
                cache_status="infrastructure_error",
                error_type="ClockError" if now is None else "InvalidTTL",
            )
            return CacheLoadResult(loader(), "infrastructure_error")

        try:
            with self._lock:
                entry = self._entries.get(key)
                expired = entry is not None and now >= entry.expires_at
                if expired:
                    self._entries.pop(key, None)
                    entry = None
                if entry is not None:
                    cached_value = entry.value
                    flight = None
                    leader = False
                else:
                    cached_value = None
                    flight = self._inflight.get(key)
                    leader = flight is None
                    if leader:
                        flight = _Flight(
                            event=Event(),
                            service=service,
                            global_generation=self._global_generation,
                            service_generation=self._service_generations.get(service, 0),
                            key_generation=self._key_generations.get(key, 0),
                        )
                        self._inflight[key] = flight
        except Exception as error:
            self._safe_event(
                "source_cache_lookup_end",
                result="error",
                started_at=started_at,
                service=service,
                dataset=dataset,
                cache_status="infrastructure_error",
                error_type=type(error).__name__,
            )
            return CacheLoadResult(loader(), "infrastructure_error")

        if cached_value is not None:
            copied, copy_ok = self._safe_copy(cached_value)
            if copy_ok:
                self._safe_event(
                    "source_cache_lookup_end",
                    result="cache_hit",
                    started_at=started_at,
                    service=service,
                    dataset=dataset,
                    cache_status="hit",
                )
                return CacheLoadResult(copied, "hit")
            self._safe_event(
                "source_cache_lookup_end",
                result="error",
                started_at=started_at,
                service=service,
                dataset=dataset,
                cache_status="infrastructure_error",
                error_type="DeepcopyError",
            )
            try:
                with self._lock:
                    current = self._entries.get(key)
                    if current is not None and current.value is cached_value:
                        self._entries.pop(key, None)
                    flight = self._inflight.get(key)
                    leader = flight is None
                    if leader:
                        flight = _Flight(
                            event=Event(),
                            service=service,
                            global_generation=self._global_generation,
                            service_generation=self._service_generations.get(service, 0),
                            key_generation=self._key_generations.get(key, 0),
                        )
                        self._inflight[key] = flight
            except Exception:
                return CacheLoadResult(loader(), "infrastructure_error")
            if not leader:
                return self._wait_for_flight(
                    flight,
                    started_at=started_at,
                    service=service,
                    dataset=dataset,
                )
            return self._load_as_leader(
                key=key,
                ttl_seconds=float(ttl_seconds),
                loader=loader,
                is_cacheable=is_cacheable,
                service=service,
                dataset=dataset,
                flight=flight,
                lookup_status="miss",
            )

        if not leader:
            return self._wait_for_flight(
                flight,
                started_at=started_at,
                service=service,
                dataset=dataset,
            )

        lookup_status = "expired" if expired else "miss"
        self._safe_event(
            "source_cache_lookup_end",
            result="cache_miss",
            started_at=started_at,
            service=service,
            dataset=dataset,
            cache_status=lookup_status,
        )
        return self._load_as_leader(
            key=key,
            ttl_seconds=float(ttl_seconds),
            loader=loader,
            is_cacheable=is_cacheable,
            service=service,
            dataset=dataset,
            flight=flight,
            lookup_status=lookup_status,
        )

    def _load_as_leader(
        self,
        *,
        key,
        ttl_seconds,
        loader,
        is_cacheable,
        service,
        dataset,
        flight,
        lookup_status,
    ) -> CacheLoadResult:
        store_started_at = self._safe_started_at()
        try:
            value = loader()
        except BaseException as error:
            flight.error = error
            self._finish_flight(key, flight)
            raise

        cacheable = False
        try:
            cacheable = bool(is_cacheable(value))
        except Exception:
            cacheable = False

        snapshot, copy_ok = self._safe_copy(value)
        if not copy_ok:
            flight.error = CacheCopyError("source cache value cannot be copied safely")
            self._safe_event(
                "source_cache_store_end",
                result="error",
                started_at=store_started_at,
                service=service,
                dataset=dataset,
                cache_status="store_error",
                error_type="DeepcopyError",
            )
            self._finish_flight(key, flight)
            return CacheLoadResult(value, "infrastructure_error")

        flight.value = snapshot
        stored = False
        invalidated = False
        if cacheable:
            expires_at = self._safe_clock()
            if expires_at is not None:
                expires_at += ttl_seconds
                try:
                    with self._lock:
                        unchanged = (
                            flight.global_generation == self._global_generation
                            and flight.service_generation
                            == self._service_generations.get(service, 0)
                            and flight.key_generation == self._key_generations.get(key, 0)
                        )
                        if unchanged:
                            self._entries[key] = _Entry(snapshot, expires_at)
                            stored = True
                        else:
                            invalidated = True
                except Exception:
                    stored = False

        if stored:
            self._safe_event(
                "source_cache_store_end",
                result="success",
                started_at=store_started_at,
                service=service,
                dataset=dataset,
                cache_status="stored",
            )
        else:
            status = (
                "not_cacheable"
                if not cacheable or invalidated
                else "store_error"
            )
            self._safe_event(
                "source_cache_store_end",
                result="fallback" if status == "not_cacheable" else "error",
                started_at=store_started_at,
                service=service,
                dataset=dataset,
                cache_status=status,
                error_type=None if status == "not_cacheable" else "CacheStoreError",
            )

        self._finish_flight(key, flight)
        if stored:
            result_status = lookup_status
        elif not cacheable or invalidated:
            result_status = "not_cacheable"
        else:
            result_status = "infrastructure_error"
        return CacheLoadResult(value, result_status)

    def _wait_for_flight(
        self, flight, *, started_at, service, dataset
    ) -> CacheLoadResult:
        flight.event.wait()
        if flight.error is not None:
            self._safe_event(
                "source_cache_lookup_end",
                result="error",
                started_at=started_at,
                service=service,
                dataset=dataset,
                cache_status="infrastructure_error",
                error_type=type(flight.error).__name__,
            )
            raise flight.error
        copied, copy_ok = self._safe_copy(flight.value)
        if not copy_ok:
            self._safe_event(
                "source_cache_lookup_end",
                result="error",
                started_at=started_at,
                service=service,
                dataset=dataset,
                cache_status="infrastructure_error",
                error_type="DeepcopyError",
            )
            raise CacheCopyError("source cache follower value cannot be copied safely")
        self._safe_event(
            "source_cache_lookup_end",
            result="cache_hit",
            started_at=started_at,
            service=service,
            dataset=dataset,
            cache_status="loader_wait",
        )
        return CacheLoadResult(copied, "loader_wait")

    def _finish_flight(self, key, flight) -> None:
        try:
            with self._lock:
                if self._inflight.get(key) is flight:
                    self._inflight.pop(key, None)
        except Exception:
            pass
        finally:
            flight.event.set()

    def clear_all(self) -> None:
        with self._lock:
            self._entries.clear()
            self._global_generation += 1

    def clear_service(self, service: str) -> None:
        with self._lock:
            keys = [key for key in self._entries if self._key_service(key) == service]
            for key in keys:
                self._entries.pop(key, None)
            self._service_generations[service] = (
                self._service_generations.get(service, 0) + 1
            )

    def clear_key(self, key: Hashable) -> None:
        with self._lock:
            self._entries.pop(key, None)
            self._key_generations[key] = self._key_generations.get(key, 0) + 1

    @staticmethod
    def _key_service(key) -> str | None:
        return key[0] if isinstance(key, tuple) and key and isinstance(key[0], str) else None

    def _safe_clock(self) -> float | None:
        try:
            value = self._clock()
            if isinstance(value, bool):
                return None
            value = float(value)
            return value if math.isfinite(value) and value >= 0 else None
        except Exception:
            return None

    def _safe_started_at(self):
        try:
            return perf_counter()
        except Exception:
            return None

    @staticmethod
    def _valid_ttl(value) -> bool:
        try:
            return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _safe_copy(value) -> tuple[Any, bool]:
        try:
            return deepcopy(value), True
        except Exception:
            return value, False

    @staticmethod
    def _safe_event(event, *, result, started_at, **fields) -> None:
        try:
            log_event(
                logger,
                event,
                result=result,
                elapsed=elapsed_ms(started_at),
                **fields,
            )
        except Exception:
            return


_DEFAULT_CACHE = SourceCacheService()


def get_or_load(**kwargs) -> CacheLoadResult:
    return _DEFAULT_CACHE.get_or_load(**kwargs)


def clear_all() -> None:
    _DEFAULT_CACHE.clear_all()


def clear_service(service: str) -> None:
    _DEFAULT_CACHE.clear_service(service)


def clear_key(key: Hashable) -> None:
    _DEFAULT_CACHE.clear_key(key)
