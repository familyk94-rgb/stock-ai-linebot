from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from contextvars import copy_context as real_copy_context
from copy import deepcopy
from collections import Counter
import logging
import threading
import time

import pytest
import requests

from core import observability
from services import (
    fundamental_service,
    market_service,
    technical_service,
)


PRICE = {
    "date": "2026-07-14",
    "close": 100,
    "open": 99,
    "max": 101,
    "min": 98,
    "change": 1,
    "change_percent": 1,
    "volume": 1000,
}
ASSET = {"type": "stock", "source": "twse_company", "confidence": "high"}
TECHNICAL = {
    "trend": "up",
    "ma_signal": "above-ma",
    "macd_signal": "positive",
    "rsi_signal": "healthy",
    "rsi": 55,
}
FINANCIAL = {"available": True, "score": 70, "marker": "financial"}
INSTITUTION = {"available": True, "score": 60, "marker": "institution"}
NEWS = {"available": True, "score": 50, "marker": "news"}
REAL_TECHNICAL_WRAPPER = market_service._get_technical_analysis
REAL_SHOPKEEPER_UPDATE = market_service._update_shopkeeper_message
INITIAL_SHOPKEEPER_MESSAGE = "原始店長訊息。"
EXPECTED_SHOPKEEPER_MESSAGE = (
    "目前技術與整體訊號偏多，可分批觀察，仍需留意風險。"
)
COMPLETE_CORE = {
    "score": 80,
    "health_score": 78,
    "consensus_score": 75,
    "decision": "偏多",
    "risk": {"risk_score": 35, "risk_level": "中低風險"},
    "risk_score": 35,
    "risk_level": "中低風險",
    "confidence": 72,
    "shopkeeper_message": INITIAL_SHOPKEEPER_MESSAGE,
}


class ApiResponse:
    def __init__(self, data=None, *, status=200, status_code=200):
        self.data = [] if data is None else data
        self.status = status
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return {"status": self.status, "data": self.data}


def _history_rows(count=70):
    return [
        {
            "date": f"2026-05-{(index % 28) + 1:02d}",
            "close": 100 + index / 10,
            "max": 101 + index / 10,
            "min": 99 + index / 10,
        }
        for index in range(count)
    ]


def _install_full_http_mocks(monkeypatch, *, asset_type="stock", history_timeout=False):
    calls = []
    price_calls = 0

    def http_get(url, params, **kwargs):
        nonlocal price_calls
        dataset = params["dataset"]
        if dataset == "TaiwanStockPrice":
            price_calls += 1
            kind = "current_price" if price_calls == 1 else "history"
            calls.append(kind)
            if kind == "history" and history_timeout:
                raise requests.Timeout("history timeout")
            if kind == "current_price":
                return ApiResponse(
                    [{
                        "date": "2026-07-14",
                        "close": 100,
                        "open": 99,
                        "max": 101,
                        "min": 98,
                        "Trading_Volume": 1000,
                    }]
                )
            return ApiResponse(_history_rows())
        if dataset in {
            "TaiwanStockPER",
            "TaiwanStockMonthRevenue",
            "TaiwanStockFinancialStatements",
        }:
            calls.append(dataset)
            return ApiResponse([])
        if dataset == "TaiwanStockInstitutionalInvestorsBuySell":
            calls.append("institution")
            return ApiResponse([])
        if dataset == "TaiwanStockNews":
            calls.append("news")
            return ApiResponse([])
        raise AssertionError(f"unexpected dataset: {dataset}")

    monkeypatch.setattr(requests, "get", http_get)
    monkeypatch.setattr(market_service, "get_stock_name", lambda stock_id: "name")
    monkeypatch.setattr(
        market_service,
        "_get_asset",
        lambda service, stock_id: {
            "type": asset_type,
            "source": "official_cache",
            "confidence": "high",
        },
    )
    monkeypatch.setattr(
        market_service,
        "_get_ai_core_analysis",
        lambda data: {"score": 70, "decision": "hold", "confidence": 60},
    )
    return calls


def _patch_market(monkeypatch):
    monkeypatch.setattr(market_service, "get_stock_name", lambda stock_id: "name")
    monkeypatch.setattr(market_service, "get_stock_info", lambda stock_id: dict(PRICE))
    monkeypatch.setattr(market_service, "_get_asset", lambda service, stock_id: dict(ASSET))
    monkeypatch.setattr(market_service, "_get_technical_analysis", lambda stock_id: dict(TECHNICAL))
    monkeypatch.setattr(
        market_service,
        "_get_fundamental_analysis",
        lambda engine, stock_id, asset: dict(FINANCIAL),
    )
    monkeypatch.setattr(
        market_service,
        "_get_institution_analysis",
        lambda engine, stock_id: dict(INSTITUTION),
    )
    monkeypatch.setattr(
        market_service,
        "_get_news_analysis",
        lambda engine, stock_id: dict(NEWS),
    )
    monkeypatch.setattr(
        market_service,
        "_get_ai_core_analysis",
        lambda data: {"score": 80, "decision": "hold", "shopkeeper_message": "old"},
    )
    monkeypatch.setattr(
        market_service,
        "_get_composite_analysis",
        lambda engine, technical, financial, institution, news: {
            "available": True,
            "score": 65,
            "summary": "composite",
            "coverage": 100,
        },
    )
    monkeypatch.setattr(market_service, "_update_shopkeeper_message", lambda data: None)
    monkeypatch.setattr(
        market_service,
        "_get_data_quality",
        lambda engine, data: {"status": "normal", "data_completeness": 100},
    )


def _parallel_results(monkeypatch, workers):
    monkeypatch.setattr(market_service, "_get_technical_analysis", workers["technical"])
    monkeypatch.setattr(market_service, "_get_fundamental_analysis", workers["fundamental"])
    monkeypatch.setattr(market_service, "_get_institution_analysis", workers["institution"])
    monkeypatch.setattr(market_service, "_get_news_analysis", workers["news"])
    return market_service._run_parallel_sources(
        "2330",
        dict(ASSET),
        object(),
        object(),
        object(),
    )


def test_four_sources_overlap_with_barrier_and_executor_shuts_down(monkeypatch):
    barrier = threading.Barrier(4)
    lock = threading.Lock()
    active = 0
    maximum_active = 0
    calls = []
    shutdown_calls = []

    class TrackingExecutor:
        def __init__(self, max_workers):
            assert max_workers == 4
            self.executor = RealThreadPoolExecutor(max_workers=max_workers)

        def submit(self, *args):
            return self.executor.submit(*args)

        def shutdown(self, wait=True):
            shutdown_calls.append(wait)
            self.executor.shutdown(wait=wait)

    monkeypatch.setattr(market_service, "ThreadPoolExecutor", TrackingExecutor)

    def worker(key, result):
        def run(*args):
            nonlocal active, maximum_active
            with lock:
                calls.append(key)
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                barrier.wait(timeout=2)
                return dict(result)
            finally:
                with lock:
                    active -= 1
        return run

    workers = {
        "technical": worker("technical", TECHNICAL),
        "fundamental": worker("fundamental", FINANCIAL),
        "institution": worker("institution", INSTITUTION),
        "news": worker("news", NEWS),
    }
    result = _parallel_results(monkeypatch, workers)

    assert maximum_active == 4
    assert sorted(calls) == sorted(market_service.SOURCE_TASK_ORDER)
    assert list(result) == list(market_service.SOURCE_TASK_ORDER)
    assert result == {
        "technical": TECHNICAL,
        "fundamental": FINANCIAL,
        "institution": INSTITUTION,
        "news": NEWS,
    }
    assert shutdown_calls == [True]


@pytest.mark.parametrize(
    "delays",
    [
        {"technical": 0.01, "fundamental": 0.02, "institution": 0.03, "news": 0.04},
        {"news": 0.01, "institution": 0.02, "fundamental": 0.03, "technical": 0.04},
        {"institution": 0.01, "technical": 0.02, "news": 0.03, "fundamental": 0.04},
    ],
)
def test_completion_order_keeps_deterministic_output(monkeypatch, delays):
    values = {
        "technical": TECHNICAL,
        "fundamental": FINANCIAL,
        "institution": INSTITUTION,
        "news": NEWS,
    }

    def worker(key):
        def run(*args):
            time.sleep(delays[key])
            return deepcopy(values[key])
        return run

    result = _parallel_results(
        monkeypatch,
        {key: worker(key) for key in market_service.SOURCE_TASK_ORDER},
    )
    assert result == values
    assert list(result) == list(market_service.SOURCE_TASK_ORDER)


def test_full_output_matches_sequential_contract_fixture(monkeypatch):
    _patch_market(monkeypatch)
    monkeypatch.setattr(
        market_service,
        "_get_ai_core_analysis",
        lambda data: deepcopy(COMPLETE_CORE),
    )
    monkeypatch.setattr(
        market_service,
        "_update_shopkeeper_message",
        REAL_SHOPKEEPER_UPDATE,
    )
    monkeypatch.setattr(
        market_service,
        "get_technical_indicators",
        lambda stock_id: dict(TECHNICAL),
    )

    profiling_events = []

    def capture_event(logger, event, **fields):
        profiling_events.append((event, fields))

    monkeypatch.setattr(market_service, "log_event", capture_event)
    sequential = _independent_sequential_reference("2330")
    sequential_shopkeeper_events = [
        fields
        for event, fields in profiling_events
        if event == "shopkeeper_analysis_end"
    ]

    profiling_events.clear()
    concurrent = market_service.get_market_info("2330")
    concurrent_shopkeeper_events = [
        fields
        for event, fields in profiling_events
        if event == "shopkeeper_analysis_end"
    ]

    assert concurrent == sequential
    assert list(concurrent) == list(sequential)
    assert concurrent["core"] == sequential["core"]
    assert list(concurrent["core"]) == list(sequential["core"])
    assert concurrent["core"]["score"] == 80
    assert concurrent["core"]["decision"] == "偏多"
    assert concurrent["core"]["risk"] == sequential["core"]["risk"]
    assert concurrent["core"]["risk"] == {
        "risk_score": 35,
        "risk_level": "中低風險",
    }
    assert concurrent["core"]["confidence"] == sequential["core"]["confidence"]
    assert concurrent["core"]["confidence"] == 72
    assert (
        concurrent["core"]["shopkeeper_message"]
        == sequential["core"]["shopkeeper_message"]
    )
    assert concurrent["core"]["shopkeeper_message"] != INITIAL_SHOPKEEPER_MESSAGE
    assert concurrent["core"]["shopkeeper_message"] == EXPECTED_SHOPKEEPER_MESSAGE
    assert concurrent["financial"] == FINANCIAL
    assert concurrent["institution"] == INSTITUTION
    assert concurrent["news"] == NEWS
    assert concurrent["composite"] == sequential["composite"]
    assert concurrent["data_quality"] == sequential["data_quality"]
    assert len(sequential_shopkeeper_events) == 1
    assert sequential_shopkeeper_events[0]["result"] == "success"
    assert sequential_shopkeeper_events[0]["service"] == "shopkeeper"
    assert sequential_shopkeeper_events[0]["elapsed"] >= 0
    assert len(concurrent_shopkeeper_events) == 1
    assert concurrent_shopkeeper_events[0]["result"] == "success"
    assert concurrent_shopkeeper_events[0]["service"] == "shopkeeper"
    assert concurrent_shopkeeper_events[0]["elapsed"] >= 0


def _independent_sequential_reference(stock_id):
    fundamental_engine = market_service.FundamentalEngine()
    institution_engine = market_service.InstitutionEngine()
    news_engine = market_service.NewsEngine()
    composite_engine = market_service.CompositeAnalysisEngine()
    data_quality_engine = market_service.DataQualityEngine()
    asset_service = market_service.AssetService()

    stock_name = market_service.get_stock_name(stock_id) or ""
    asset = market_service._get_asset(asset_service, stock_id)
    stock = market_service.get_stock_info(stock_id)
    technical = market_service.get_technical_indicators(stock_id) or {}
    stock_data = {
        "stock_id": stock_id,
        "stock_code": stock_id,
        "stock_name": stock_name,
        "date": stock.get("date", "-"),
        "price": stock.get("close"),
        "open": stock.get("open"),
        "high": stock.get("max"),
        "low": stock.get("min"),
        "change": stock.get("change"),
        "change_percent": stock.get("change_percent"),
        "volume": stock.get("volume"),
        "price_text": market_service.format_price(stock.get("close")),
        "open_text": market_service.format_price(stock.get("open")),
        "high_text": market_service.format_price(stock.get("max")),
        "low_text": market_service.format_price(stock.get("min")),
        "volume_text": market_service.format_number(stock.get("volume")),
        "trend": technical.get("trend", "技術分析中"),
        "ma_signal": technical.get("ma_signal", "技術分析中"),
        "macd_signal": technical.get("macd_signal", "技術分析中"),
        "rsi_signal": technical.get("rsi_signal", "技術分析中"),
        "technical": technical,
        "asset": asset,
    }
    stock_data["core"] = market_service._get_ai_core_analysis(stock_data)
    stock_data["financial"] = market_service._get_fundamental_analysis(
        fundamental_engine, stock_id, asset
    )
    stock_data["institution"] = market_service._get_institution_analysis(
        institution_engine, stock_id
    )
    stock_data["news"] = market_service._get_news_analysis(news_engine, stock_id)
    stock_data["composite"] = market_service._get_composite_analysis(
        composite_engine,
        {
            "available": bool(stock_data.get("technical")),
            "score": (stock_data.get("core") or {}).get("score"),
        },
        stock_data["financial"],
        stock_data["institution"],
        stock_data["news"],
    )
    market_service._update_shopkeeper_message(stock_data)
    stock_data["data_quality"] = market_service._get_data_quality(
        data_quality_engine, stock_data
    )
    return stock_data


def test_ai_core_input_excludes_later_source_results(monkeypatch):
    _patch_market(monkeypatch)
    seen = []

    def analyze(data):
        seen.append(deepcopy(data))
        return {"score": 80, "decision": "hold"}

    monkeypatch.setattr(market_service, "_get_ai_core_analysis", analyze)
    market_service.get_market_info("2330")

    assert len(seen) == 1
    assert seen[0]["technical"] == TECHNICAL
    assert seen[0]["asset"] == ASSET
    assert seen[0]["price"] == 100
    assert not {"financial", "institution", "news", "composite", "data_quality"} & set(seen[0])


def test_composite_shopkeeper_and_quality_run_after_fixed_merge(monkeypatch):
    _patch_market(monkeypatch)
    order = []

    def composite(engine, technical, financial, institution, news):
        order.append("composite")
        assert technical == {"available": True, "score": 80}
        assert financial == FINANCIAL
        assert institution == INSTITUTION
        assert news == NEWS
        return {"available": True, "score": 65}

    def shopkeeper(data):
        order.append("shopkeeper")
        assert data["composite"] == {"available": True, "score": 65}

    def quality(engine, data):
        order.append("data_quality")
        assert all(key in data for key in ("technical", "financial", "institution", "news", "composite"))
        return {"status": "normal"}

    monkeypatch.setattr(market_service, "_get_composite_analysis", composite)
    monkeypatch.setattr(market_service, "_update_shopkeeper_message", shopkeeper)
    monkeypatch.setattr(market_service, "_get_data_quality", quality)
    market_service.get_market_info("2330")
    assert order == ["composite", "shopkeeper", "data_quality"]


def test_technical_unexpected_exception_becomes_empty_fallback(monkeypatch):
    _patch_market(monkeypatch)
    monkeypatch.setattr(
        market_service,
        "get_technical_indicators",
        lambda stock_id: (_ for _ in ()).throw(RuntimeError("technical failed")),
    )
    # Restore the real coordinator wrapper replaced by _patch_market.
    monkeypatch.setattr(
        market_service,
        "_get_technical_analysis",
        REAL_TECHNICAL_WRAPPER,
    )
    result = market_service.get_market_info("2330")
    assert result["technical"] == {}
    assert result["financial"] == FINANCIAL
    assert result["institution"] == INSTITUTION
    assert result["news"] == NEWS
    assert "core" in result and "composite" in result and "data_quality" in result
@pytest.mark.parametrize("failed", market_service.SOURCE_TASK_ORDER)
def test_each_outer_future_failure_is_isolated(monkeypatch, failed):
    values = {
        "technical": TECHNICAL,
        "fundamental": FINANCIAL,
        "institution": INSTITUTION,
        "news": NEWS,
    }

    def worker(key):
        def run(*args):
            if key == failed:
                raise RuntimeError(f"{key} failed")
            return deepcopy(values[key])
        return run

    events = []
    monkeypatch.setattr(
        market_service,
        "log_event",
        lambda logger, event, **fields: events.append((event, fields)),
    )
    result = _parallel_results(
        monkeypatch,
        {key: worker(key) for key in market_service.SOURCE_TASK_ORDER},
    )
    expected_fallback = {
        "technical": {},
        "fundamental": market_service._fundamental_fallback(ASSET),
        "institution": market_service._institution_fallback(),
        "news": market_service._news_fallback(),
    }
    assert result[failed] == expected_fallback[failed]
    for key in set(values) - {failed}:
        assert result[key] == values[key]
    event_name = {
        "technical": "technical_analysis_end",
        "fundamental": "fundamental_analysis_end",
        "institution": "institution_analysis_end",
        "news": "news_analysis_end",
    }[failed]
    matches = [fields for event, fields in events if event == event_name]
    assert len(matches) == 1
    assert matches[0]["result"] == "fallback"
    assert matches[0]["error_type"] == "RuntimeError"


def test_multiple_source_failures_are_isolated(monkeypatch):
    def fail(*args):
        raise RuntimeError("failed")

    result = _parallel_results(
        monkeypatch,
        {
            "technical": fail,
            "fundamental": lambda *args: dict(FINANCIAL),
            "institution": fail,
            "news": lambda *args: dict(NEWS),
        },
    )
    assert result["technical"] == {}
    assert result["fundamental"] == FINANCIAL
    assert result["institution"] == market_service._institution_fallback()
    assert result["news"] == NEWS


def test_submit_failure_only_falls_back_failed_stage(monkeypatch):
    real_executor = RealThreadPoolExecutor

    class SubmitFailureExecutor:
        def __init__(self, max_workers):
            assert max_workers == 4
            self.executor = real_executor(max_workers=max_workers)

        def submit(self, function, worker, *args):
            if worker is market_service._get_institution_analysis:
                raise RuntimeError("submit failed")
            return self.executor.submit(function, worker, *args)

        def shutdown(self, wait=True):
            self.executor.shutdown(wait=wait)

    monkeypatch.setattr(market_service, "ThreadPoolExecutor", SubmitFailureExecutor)
    _patch_market(monkeypatch)
    events = []
    monkeypatch.setattr(
        market_service,
        "log_event",
        lambda logger, event, **fields: events.append((event, fields)),
    )
    result = market_service.get_market_info("2330")
    assert result["technical"] == TECHNICAL
    assert result["financial"] == FINANCIAL
    assert result["institution"] == market_service._institution_fallback()
    assert result["news"] == NEWS
    matches = [
        fields for event, fields in events if event == "institution_analysis_end"
    ]
    assert len(matches) == 1
    assert matches[0]["result"] == "fallback"
    assert matches[0]["error_type"] == "RuntimeError"


def test_executor_creation_failure_returns_all_fallbacks(monkeypatch):
    monkeypatch.setattr(
        market_service,
        "ThreadPoolExecutor",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("executor failed")),
    )
    result = market_service._run_parallel_sources(
        "2330", ASSET, object(), object(), object()
    )
    assert result == {
        "technical": {},
        "fundamental": market_service._fundamental_fallback(ASSET),
        "institution": market_service._institution_fallback(),
        "news": market_service._news_fallback(),
    }


def test_shutdown_failure_does_not_discard_results(monkeypatch):
    class ShutdownFailureExecutor:
        def __init__(self, max_workers):
            self.executor = RealThreadPoolExecutor(max_workers=max_workers)

        def submit(self, *args):
            return self.executor.submit(*args)

        def shutdown(self, wait=True):
            self.executor.shutdown(wait=wait)
            raise RuntimeError("shutdown failed")

    monkeypatch.setattr(market_service, "ThreadPoolExecutor", ShutdownFailureExecutor)
    _patch_market(monkeypatch)
    result = market_service.get_market_info("2330")
    assert result["technical"] == TECHNICAL
    assert result["financial"] == FINANCIAL
    assert result["institution"] == INSTITUTION
    assert result["news"] == NEWS


def test_each_worker_has_independent_context_and_same_request_id(monkeypatch):
    contexts = []
    request_ids = []

    def tracked_copy_context():
        context = real_copy_context()
        contexts.append(context)
        return context

    def worker(value):
        def run(*args):
            request_ids.append(observability.get_request_id())
            return dict(value)
        return run

    monkeypatch.setattr(market_service, "copy_context", tracked_copy_context)
    token = observability.set_request_id("parallel-request")
    try:
        _parallel_results(
            monkeypatch,
            {
                "technical": worker(TECHNICAL),
                "fundamental": worker(FINANCIAL),
                "institution": worker(INSTITUTION),
                "news": worker(NEWS),
            },
        )
        assert observability.get_request_id() == "parallel-request"
    finally:
        observability.clear_request_id(token)

    assert len(contexts) == 4
    assert len({id(context) for context in contexts}) == 4
    assert request_ids == ["parallel-request"] * 4


def test_different_request_contexts_do_not_mix(monkeypatch):
    lock = threading.Lock()
    seen = {"request-a": [], "request-b": []}

    def worker(value):
        def run(*args):
            request_id = observability.get_request_id()
            with lock:
                seen[request_id].append(request_id)
            return dict(value)
        return run

    workers = {
        "technical": worker(TECHNICAL),
        "fundamental": worker(FINANCIAL),
        "institution": worker(INSTITUTION),
        "news": worker(NEWS),
    }
    monkeypatch.setattr(market_service, "_get_technical_analysis", workers["technical"])
    monkeypatch.setattr(market_service, "_get_fundamental_analysis", workers["fundamental"])
    monkeypatch.setattr(market_service, "_get_institution_analysis", workers["institution"])
    monkeypatch.setattr(market_service, "_get_news_analysis", workers["news"])

    def request(request_id):
        token = observability.set_request_id(request_id)
        try:
            market_service._run_parallel_sources(
                "2330", ASSET, object(), object(), object()
            )
        finally:
            observability.clear_request_id(token)

    parents = [
        threading.Thread(target=request, args=("request-a",)),
        threading.Thread(target=request, args=("request-b",)),
    ]
    for parent in parents:
        parent.start()
    for parent in parents:
        parent.join(timeout=3)

    assert all(not parent.is_alive() for parent in parents)
    assert seen == {
        "request-a": ["request-a"] * 4,
        "request-b": ["request-b"] * 4,
    }


def test_no_price_branch_does_not_create_executor_or_run_technical(monkeypatch):
    monkeypatch.setattr(market_service, "get_stock_name", lambda stock_id: "name")
    monkeypatch.setattr(market_service, "_get_asset", lambda service, stock_id: dict(ASSET))
    monkeypatch.setattr(market_service, "get_stock_info", lambda stock_id: None)
    monkeypatch.setattr(
        market_service,
        "ThreadPoolExecutor",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("executor must not run")),
    )
    monkeypatch.setattr(
        market_service,
        "get_technical_indicators",
        lambda stock_id: (_ for _ in ()).throw(AssertionError("technical must not run")),
    )
    calls = []
    monkeypatch.setattr(
        market_service,
        "_get_fundamental_analysis",
        lambda *args: calls.append("fundamental") or dict(FINANCIAL),
    )
    monkeypatch.setattr(
        market_service,
        "_get_institution_analysis",
        lambda *args: calls.append("institution") or dict(INSTITUTION),
    )
    monkeypatch.setattr(
        market_service,
        "_get_news_analysis",
        lambda *args: calls.append("news") or dict(NEWS),
    )
    monkeypatch.setattr(
        market_service,
        "_get_composite_analysis",
        lambda *args: {"available": False, "score": 50},
    )
    monkeypatch.setattr(
        market_service,
        "_get_data_quality",
        lambda *args: {"status": "insufficient"},
    )
    result = market_service.get_market_info("2330")
    assert calls == ["fundamental", "institution", "news"]
    assert result["price"] is None
    assert result["technical"] == {}
    assert "core" in result and "composite" in result and "data_quality" in result


def test_logging_and_elapsed_failures_do_not_change_parallel_results(monkeypatch):
    _patch_market(monkeypatch)
    monkeypatch.setattr(
        market_service,
        "log_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("logging failed")),
    )
    monkeypatch.setattr(
        market_service,
        "elapsed_ms",
        lambda value: (_ for _ in ()).throw(RuntimeError("elapsed failed")),
    )
    result = market_service.get_market_info("2330")
    assert result["technical"] == TECHNICAL
    assert result["financial"] == FINANCIAL
    assert result["institution"] == INSTITUTION
    assert result["news"] == NEWS


def test_real_history_timeout_isolated_with_exact_events(monkeypatch, caplog):
    calls = _install_full_http_mocks(monkeypatch, history_timeout=True)
    with caplog.at_level(logging.INFO):
        result = market_service.get_market_info("2330")

    assert result["price"] == 100
    assert result["technical"] == {}
    assert "financial" in result and "institution" in result and "news" in result
    assert "core" in result and "composite" in result and "data_quality" in result
    assert Counter(calls) == Counter(
        {
            "current_price": 1,
            "history": 1,
            "TaiwanStockPER": 1,
            "TaiwanStockMonthRevenue": 1,
            "TaiwanStockFinancialStatements": 1,
            "institution": 1,
            "news": 1,
        }
    )
    messages = [record.getMessage() for record in caplog.records]
    history_events = [
        message for message in messages if "event=price_history_request_end" in message
    ]
    technical_events = [
        message for message in messages if "event=technical_analysis_end" in message
    ]
    market_events = [
        message for message in messages if "event=market_service_end" in message
    ]
    assert len(history_events) == 1
    assert "result=timeout" in history_events[0]
    assert "error_type=Timeout" in history_events[0]
    assert len(technical_events) == 1
    assert "result=fallback" in technical_events[0]
    assert len(market_events) == 1
    assert "result=success" in market_events[0]


def test_stock_market_full_api_call_count_is_exactly_seven(monkeypatch):
    calls = _install_full_http_mocks(monkeypatch, asset_type="stock")
    result = market_service.get_market_info("2330")
    assert result["price"] == 100
    assert Counter(calls) == Counter(
        {
            "current_price": 1,
            "history": 1,
            "TaiwanStockPER": 1,
            "TaiwanStockMonthRevenue": 1,
            "TaiwanStockFinancialStatements": 1,
            "institution": 1,
            "news": 1,
        }
    )
    assert len(calls) == 7


def test_etf_market_full_api_call_count_is_exactly_four(monkeypatch):
    calls = _install_full_http_mocks(monkeypatch, asset_type="etf")
    result = market_service.get_market_info("0050")
    assert result["price"] == 100
    assert result["financial"]["applicability"] == "not_applicable"
    assert Counter(calls) == Counter(
        {"current_price": 1, "history": 1, "institution": 1, "news": 1}
    )
    assert len(calls) == 4
    assert not {
        "TaiwanStockPER",
        "TaiwanStockMonthRevenue",
        "TaiwanStockFinancialStatements",
    } & set(calls)


def test_market_to_fundamental_inner_workers_preserve_request_id(
    monkeypatch,
    caplog,
):
    _install_full_http_mocks(monkeypatch, asset_type="stock")
    top_contexts = []
    inner_contexts = []
    inner_request_ids = []

    def top_copy_context():
        context = real_copy_context()
        top_contexts.append(context)
        return context

    def inner_copy_context():
        context = real_copy_context()
        inner_contexts.append(context)
        return context

    base_http_get = requests.get

    def observing_http_get(url, params, **kwargs):
        if params["dataset"] in {
            "TaiwanStockPER",
            "TaiwanStockMonthRevenue",
            "TaiwanStockFinancialStatements",
        }:
            inner_request_ids.append(
                (params["dataset"], observability.get_request_id())
            )
        return base_http_get(url, params, **kwargs)

    monkeypatch.setattr(market_service, "copy_context", top_copy_context)
    monkeypatch.setattr(fundamental_service, "copy_context", inner_copy_context)
    monkeypatch.setattr(requests, "get", observing_http_get)
    token = observability.set_request_id("nested-fundamental")
    try:
        with caplog.at_level(logging.INFO):
            result = market_service.get_market_info("2330")
    finally:
        observability.clear_request_id(token)

    assert result["price"] == 100
    assert Counter(inner_request_ids) == Counter(
        {
            ("TaiwanStockPER", "nested-fundamental"): 1,
            ("TaiwanStockMonthRevenue", "nested-fundamental"): 1,
            ("TaiwanStockFinancialStatements", "nested-fundamental"): 1,
        }
    )
    assert len(top_contexts) == 4
    assert len({id(context) for context in top_contexts}) == 4
    assert len(inner_contexts) == 3
    assert len({id(context) for context in inner_contexts}) == 3
    assert not {id(context) for context in top_contexts} & {
        id(context) for context in inner_contexts
    }
    messages = [record.getMessage() for record in caplog.records]
    dataset_events = [
        message
        for message in messages
        if "event=finmind_request_end" in message
        and "service=fundamental" in message
    ]
    fundamental_events = [
        message for message in messages if "event=fundamental_analysis_end" in message
    ]
    market_events = [
        message for message in messages if "event=market_service_end" in message
    ]
    assert len(dataset_events) == 3
    assert len(fundamental_events) == 1
    assert len(market_events) == 1
    assert all("request_id=nested-fundamental" in message for message in dataset_events)
    assert "request_id=nested-fundamental" in fundamental_events[0]
    assert "request_id=nested-fundamental" in market_events[0]


def _patch_real_technical_path(monkeypatch):
    _patch_market(monkeypatch)
    monkeypatch.setattr(
        market_service,
        "_get_technical_analysis",
        REAL_TECHNICAL_WRAPPER,
    )
    monkeypatch.setattr(
        technical_service,
        "_calculate_technical_indicators",
        lambda stock_id: deepcopy(TECHNICAL),
    )


def test_real_technical_logging_handler_failure_preserves_result(monkeypatch):
    _patch_real_technical_path(monkeypatch)
    failures = []

    class BrokenHandler(logging.Handler):
        def emit(self, record):
            failures.append(record.getMessage())
            raise RuntimeError("handler failed")

    handler = BrokenHandler()
    logger = technical_service.logger
    original_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        result = market_service.get_market_info("2330")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)

    assert len(failures) == 1
    assert "event=technical_analysis_end" in failures[0]
    assert result["technical"] == TECHNICAL
    assert result["financial"] == FINANCIAL
    assert result["institution"] == INSTITUTION
    assert result["news"] == NEWS
    assert "core" in result and "composite" in result and "data_quality" in result


def test_real_technical_elapsed_clock_failure_preserves_result(
    monkeypatch,
    caplog,
):
    _patch_real_technical_path(monkeypatch)
    monkeypatch.setattr(
        observability,
        "perf_counter",
        lambda: (_ for _ in ()).throw(RuntimeError("clock failed")),
    )
    with caplog.at_level(logging.INFO):
        result = market_service.get_market_info("2330")

    technical_events = [
        record.getMessage()
        for record in caplog.records
        if "event=technical_analysis_end" in record.getMessage()
    ]
    assert len(technical_events) == 1
    assert "result=success" in technical_events[0]
    assert "elapsed_ms=0" in technical_events[0]
    assert result["technical"] == TECHNICAL
    assert result["financial"] == FINANCIAL
    assert result["institution"] == INSTITUTION
    assert result["news"] == NEWS
