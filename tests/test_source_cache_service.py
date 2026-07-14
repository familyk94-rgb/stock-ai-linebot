import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy as real_deepcopy

import pytest

from core import observability
from services import source_cache_service
from services.source_cache_service import SourceCacheService


KEY = ("fundamental", "v1", "TaiwanStockPER", "2330", 45)


class Clock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


def _load(cache, loader, *, key=KEY, eligible=lambda value: True):
    return cache.get_or_load(
        key=key,
        ttl_seconds=300,
        loader=loader,
        is_cacheable=eligible,
        service="fundamental",
        dataset=key[2],
    )


def test_cold_miss_then_warm_hit_and_call_once():
    cache = SourceCacheService(clock=Clock())
    calls = []

    def loader():
        calls.append(1)
        return [{"nested": [1]}]

    first = _load(cache, loader)
    second = _load(cache, loader)
    assert first.cache_status == "miss"
    assert second.cache_status == "hit"
    assert first.value == second.value == [{"nested": [1]}]
    assert len(calls) == 1


@pytest.mark.parametrize("advance", [300, 301])
def test_exact_expiry_and_later_are_misses(advance):
    clock = Clock()
    cache = SourceCacheService(clock=clock)
    calls = []
    _load(cache, lambda: calls.append(1) or [{"value": 1}])
    clock.value += advance
    result = _load(cache, lambda: calls.append(2) or [{"value": 2}])
    assert result.cache_status == "expired"
    assert result.value == [{"value": 2}]
    assert calls == [1, 2]


def test_different_keys_load_concurrently():
    cache = SourceCacheService(clock=Clock())
    barrier = threading.Barrier(2)
    active = 0
    maximum = 0
    lock = threading.Lock()

    def loader(value):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            barrier.wait(timeout=2)
            return [{"value": value}]
        finally:
            with lock:
                active -= 1

    keys = [
        ("fundamental", "v1", "TaiwanStockPER", "2330", 45),
        ("fundamental", "v1", "TaiwanStockPER", "2317", 45),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_load, cache, lambda value=value: loader(value), key=key)
            for value, key in enumerate(keys)
        ]
        assert [future.result().value for future in futures] == [
            [{"value": 0}],
            [{"value": 1}],
        ]
    assert maximum == 2


def test_same_key_single_flight_loader_once_and_follower_copy():
    cache = SourceCacheService(clock=Clock())
    started = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        started.set()
        assert release.wait(timeout=2)
        return [{"nested": [1]}]

    with ThreadPoolExecutor(max_workers=3) as executor:
        leader = executor.submit(_load, cache, loader)
        assert started.wait(timeout=2)
        followers = [executor.submit(_load, cache, loader) for _ in range(2)]
        time.sleep(0.02)
        release.set()
        results = [leader.result(), *(future.result() for future in followers)]

    assert len(calls) == 1
    assert results[0].cache_status == "miss"
    assert all(result.cache_status == "loader_wait" for result in results[1:])
    assert all(result.value == [{"nested": [1]}] for result in results)
    assert len({id(result.value) for result in results}) == 3
    results[1].value[0]["nested"].append(2)
    assert results[2].value == [{"nested": [1]}]
    assert cache._inflight == {}


def test_noncacheable_single_flight_still_loads_once_per_wave():
    cache = SourceCacheService(clock=Clock())
    started = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        started.set()
        release.wait(timeout=2)
        return []

    with ThreadPoolExecutor(max_workers=2) as executor:
        leader = executor.submit(_load, cache, loader, eligible=lambda value: bool(value))
        started.wait(timeout=2)
        follower = executor.submit(_load, cache, loader, eligible=lambda value: bool(value))
        time.sleep(0.02)
        release.set()
        assert leader.result().value == []
        assert follower.result().value == []
    assert len(calls) == 1
    assert _load(cache, loader, eligible=lambda value: bool(value)).cache_status == "not_cacheable"
    assert len(calls) == 2


def test_leader_exception_releases_followers_and_cleans_inflight():
    cache = SourceCacheService(clock=Clock())
    started = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        started.set()
        release.wait(timeout=2)
        raise RuntimeError("failed")

    with ThreadPoolExecutor(max_workers=2) as executor:
        leader = executor.submit(_load, cache, loader)
        started.wait(timeout=2)
        follower = executor.submit(_load, cache, loader)
        time.sleep(0.02)
        release.set()
        with pytest.raises(RuntimeError):
            leader.result()
        with pytest.raises(RuntimeError):
            follower.result()
    assert calls == [1]
    assert cache._inflight == {}


def test_deepcopy_on_write_and_read_protects_nested_values():
    cache = SourceCacheService(clock=Clock())
    original = [{"nested": [1]}]
    first = _load(cache, lambda: original)
    original[0]["nested"].append(2)
    first.value[0]["nested"].append(3)
    second = _load(cache, lambda: pytest.fail("must hit"))
    assert second.value == [{"nested": [1]}]
    second.value[0]["nested"].append(4)
    third = _load(cache, lambda: pytest.fail("must hit"))
    assert third.value == [{"nested": [1]}]


def test_deepcopy_failure_returns_loader_value_without_caching():
    class Uncopyable:
        def __deepcopy__(self, memo):
            raise RuntimeError("copy failed")

    cache = SourceCacheService(clock=Clock())
    calls = []
    value = Uncopyable()
    first = _load(cache, lambda: calls.append(1) or value)
    second = _load(cache, lambda: calls.append(2) or value)
    assert first.value is value and second.value is value
    assert first.cache_status == second.cache_status == "infrastructure_error"
    assert calls == [1, 2]
    assert cache._entries == {}


def test_write_copy_failure_gives_leader_result_and_follower_safe_exception(
    monkeypatch,
):
    cache = SourceCacheService(clock=Clock())
    started = threading.Event()
    release = threading.Event()
    value = [{"nested": [1]}]
    calls = []

    def loader():
        calls.append(1)
        started.set()
        release.wait(timeout=2)
        return value

    monkeypatch.setattr(
        source_cache_service,
        "deepcopy",
        lambda item: (_ for _ in ()).throw(RuntimeError("copy")),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        leader = executor.submit(_load, cache, loader)
        assert started.wait(timeout=2)
        follower = executor.submit(_load, cache, loader)
        time.sleep(0.02)
        release.set()
        leader_result = leader.result()
        with pytest.raises(source_cache_service.CacheCopyError):
            follower.result()
    assert leader_result.value is value
    assert calls == [1]
    assert cache._entries == {}
    assert cache._inflight == {}
    monkeypatch.setattr(source_cache_service, "deepcopy", real_deepcopy)
    next_result = _load(cache, lambda: calls.append(2) or [{"nested": [2]}])
    assert next_result.cache_status == "miss"
    assert next_result.value == [{"nested": [2]}]
    assert calls == [1, 2]


def test_follower_copy_failure_never_returns_leader_reference(monkeypatch):
    cache = SourceCacheService(clock=Clock())
    started = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        started.set()
        release.wait(timeout=2)
        return [{"nested": [1]}]

    def controlled_copy(value):
        if threading.current_thread().name.endswith("_1"):
            raise RuntimeError("follower copy")
        return real_deepcopy(value)

    monkeypatch.setattr(source_cache_service, "deepcopy", controlled_copy)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="copy") as executor:
        leader = executor.submit(_load, cache, loader)
        assert started.wait(timeout=2)
        follower = executor.submit(_load, cache, loader)
        time.sleep(0.02)
        release.set()
        leader_result = leader.result()
        with pytest.raises(source_cache_service.CacheCopyError):
            follower.result()
    assert leader_result.value == [{"nested": [1]}]
    assert calls == [1]
    assert cache._inflight == {}


def test_cache_hit_copy_failure_removes_entry_and_loads_once(monkeypatch):
    cache = SourceCacheService(clock=Clock())
    _load(cache, lambda: [{"value": 1}])
    calls = []
    copy_calls = 0
    events = []

    def fail_once(value):
        nonlocal copy_calls
        copy_calls += 1
        if copy_calls == 1:
            raise RuntimeError("read copy")
        return real_deepcopy(value)

    monkeypatch.setattr(source_cache_service, "deepcopy", fail_once)
    monkeypatch.setattr(
        source_cache_service,
        "log_event",
        lambda logger, event, **fields: events.append((event, fields)),
    )
    recovered = _load(cache, lambda: calls.append(1) or [{"value": 2}])
    warm = _load(cache, lambda: pytest.fail("recovered value must be cached"))
    assert recovered.value == warm.value == [{"value": 2}]
    assert calls == [1]
    assert recovered.cache_status == "miss"
    assert warm.cache_status == "hit"
    lookup_events = [fields for event, fields in events if event == "source_cache_lookup_end"]
    assert len(lookup_events) == 2
    assert [fields["result"] for fields in lookup_events] == ["error", "cache_hit"]


@pytest.mark.parametrize(
    "bad_clock",
    [lambda: (_ for _ in ()).throw(RuntimeError("clock")), lambda: float("nan")],
)
def test_clock_failure_degrades_to_loader_without_cache(bad_clock):
    cache = SourceCacheService(clock=bad_clock)
    calls = []
    assert _load(cache, lambda: calls.append(1) or [1]).value == [1]
    assert _load(cache, lambda: calls.append(2) or [2]).value == [2]
    assert calls == [1, 2]


def test_store_failure_returns_value_and_does_not_retry():
    class BrokenEntries(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("store")

    cache = SourceCacheService(clock=Clock())
    cache._entries = BrokenEntries()
    calls = []
    result = _load(cache, lambda: calls.append(1) or [{"value": 1}])
    assert result.value == [{"value": 1}]
    assert result.cache_status == "infrastructure_error"
    assert calls == [1]


def test_lookup_failure_degrades_to_one_loader_call():
    class BrokenLock:
        def __enter__(self):
            raise RuntimeError("lock")

        def __exit__(self, *args):
            return False

    cache = SourceCacheService(clock=Clock())
    cache._lock = BrokenLock()
    calls = []
    result = _load(cache, lambda: calls.append(1) or [{"value": 1}])
    assert result.value == [{"value": 1}]
    assert result.cache_status == "infrastructure_error"
    assert calls == [1]


def test_logging_and_elapsed_failures_do_not_change_cache(monkeypatch):
    cache = SourceCacheService(clock=Clock())
    monkeypatch.setattr(
        source_cache_service,
        "log_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("log")),
    )
    monkeypatch.setattr(
        source_cache_service,
        "elapsed_ms",
        lambda value: (_ for _ in ()).throw(RuntimeError("elapsed")),
    )
    calls = []
    assert _load(cache, lambda: calls.append(1) or [1]).value == [1]
    assert _load(cache, lambda: calls.append(2) or [2]).value == [1]
    assert calls == [1]


def test_clear_all_service_and_key_force_next_miss():
    cache = SourceCacheService(clock=Clock())
    key_a = ("fundamental", "v1", "A", "2330", 1)
    key_b = ("fundamental", "v1", "B", "2330", 1)
    key_c = ("news", "v1", "C", "2330", 1)
    for key in (key_a, key_b, key_c):
        _load(cache, lambda key=key: [key], key=key)

    cache.clear_key(key_a)
    assert _load(cache, lambda: ["new-a"], key=key_a).value == ["new-a"]
    cache.clear_service("fundamental")
    assert _load(cache, lambda: ["new-b"], key=key_b).value == ["new-b"]
    assert _load(cache, lambda: pytest.fail("news should remain"), key=key_c).cache_status == "hit"
    cache.clear_all()
    assert _load(cache, lambda: ["new-c"], key=key_c).value == ["new-c"]


def test_clear_during_flight_does_not_cancel_loader_or_store_result():
    cache = SourceCacheService(clock=Clock())
    started = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        started.set()
        release.wait(timeout=2)
        return [{"value": 1}]

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_load, cache, loader)
        started.wait(timeout=2)
        cache.clear_key(KEY)
        release.set()
        assert future.result().value == [{"value": 1}]
    result = _load(cache, lambda: calls.append(2) or [{"value": 2}])
    assert result.value == [{"value": 2}]
    assert calls == [1, 2]


@pytest.mark.parametrize("clear_method", ["clear_service", "clear_all"])
def test_service_and_all_clear_during_flight_prevent_repopulation(clear_method):
    cache = SourceCacheService(clock=Clock())
    started = threading.Event()
    release = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        started.set()
        release.wait(timeout=2)
        return [{"value": 1}]

    with ThreadPoolExecutor(max_workers=2) as executor:
        leader = executor.submit(_load, cache, loader)
        assert started.wait(timeout=2)
        follower = executor.submit(_load, cache, loader)
        time.sleep(0.02)
        if clear_method == "clear_service":
            cache.clear_service("fundamental")
        else:
            cache.clear_all()
        release.set()
        assert leader.result().value == follower.result().value == [{"value": 1}]
    assert calls == [1]
    assert cache._inflight == {}
    assert _load(cache, lambda: calls.append(2) or [{"value": 2}]).value == [
        {"value": 2}
    ]
    assert calls == [1, 2]


def test_store_clock_failure_returns_result_without_caching(monkeypatch):
    values = iter([100.0, RuntimeError("store clock"), 200.0, 200.0])

    def clock():
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return value

    cache = SourceCacheService(clock=clock)
    events = []
    monkeypatch.setattr(
        source_cache_service,
        "log_event",
        lambda logger, event, **fields: events.append((event, fields)),
    )
    calls = []
    first = _load(cache, lambda: calls.append(1) or [{"value": 1}])
    second = _load(cache, lambda: calls.append(2) or [{"value": 2}])
    assert first.value == [{"value": 1}]
    assert first.cache_status == "infrastructure_error"
    assert second.value == [{"value": 2}]
    assert calls == [1, 2]
    store_errors = [
        fields
        for event, fields in events
        if event == "source_cache_store_end"
        and fields.get("cache_status") == "store_error"
    ]
    assert len(store_errors) == 1
    assert store_errors[0]["result"] == "error"


def test_events_keep_request_id_and_exclude_key_and_sensitive_data(caplog):
    cache = SourceCacheService(clock=Clock())
    token = observability.set_request_id("cache-request")
    try:
        with caplog.at_level(logging.INFO):
            _load(cache, lambda: [{"secret": "value"}])
            _load(cache, lambda: pytest.fail("must hit"))
    finally:
        observability.clear_request_id(token)

    messages = [
        record.getMessage()
        for record in caplog.records
        if "event=source_cache_" in record.getMessage()
    ]
    assert messages
    assert all("request_id=cache-request" in message for message in messages)
    text = " ".join(messages)
    assert "2330" not in text
    assert "secret" not in text
    assert "TaiwanStockPER" in text
