import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from services import asset_service, market_service
from services.asset_service import AssetService, asset_fallback


FIXTURES = Path(__file__).parent / "fixtures" / "assets"
NOW = datetime(2026, 7, 12, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Response:
    def __init__(self, payload=None, status=200, json_error=None):
        self.payload = payload
        self.status_code = status
        self.json_error = json_error

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if self.json_error:
            raise self.json_error
        return deepcopy(self.payload)


def payloads():
    return {
        asset_service.TWSE_COMPANY_URL: fixture("twse_companies.json"),
        asset_service.TPEX_COMPANY_URL: fixture("tpex_companies.json"),
        asset_service.TWSE_ETF_URL: fixture("twse_etfs.json"),
        asset_service.TPEX_ETF_URL: fixture("tpex_etfs.json"),
    }


def install_http(monkeypatch, values=None, calls=None):
    values = values or payloads()
    calls = calls if calls is not None else []

    def request(method, url, timeout):
        calls.append((method, url, timeout))
        value = values[url]
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, Response) else Response(value)

    monkeypatch.setattr(asset_service.requests, "request", request)
    return calls


def service(tmp_path):
    return AssetService(tmp_path / "asset.json", now_provider=lambda: NOW)


@pytest.mark.parametrize("symbol", ["2330", "2317", "2303", "3481"])
def test_twse_company_fixtures_are_stocks(monkeypatch, tmp_path, symbol):
    install_http(monkeypatch)
    assert service(tmp_path).get_asset(symbol) == {
        "type": "stock",
        "source": "twse_company",
        "confidence": "high",
    }


@pytest.mark.parametrize("symbol", ["0050", "0056", "006208", "00878", "00919"])
def test_twse_etf_fixtures_are_etfs(monkeypatch, tmp_path, symbol):
    install_http(monkeypatch)
    assert service(tmp_path).get_asset(symbol) == {
        "type": "etf",
        "source": "twse_etf",
        "confidence": "high",
    }


@pytest.mark.parametrize("symbol", ["006201", "00679B", "00687B"])
def test_tpex_etf_fixtures_are_etfs(monkeypatch, tmp_path, symbol):
    install_http(monkeypatch)
    assert service(tmp_path).get_asset(symbol) == {
        "type": "etf",
        "source": "tpex_etf",
        "confidence": "high",
    }


@pytest.mark.parametrize("symbol", [None, "", "  ", "TAIEX", "TPEx", "TSE24", "009999"])
def test_unknown_symbols_are_not_guessed(monkeypatch, tmp_path, symbol):
    calls = install_http(monkeypatch)
    result = service(tmp_path).get_asset(symbol)
    assert result == asset_fallback()
    assert result["confidence"] != "high"
    if symbol is None or not str(symbol).strip():
        assert calls == []


def test_source_conflict_is_unknown(monkeypatch, tmp_path):
    values = payloads()
    values[asset_service.TWSE_COMPANY_URL].append({"公司代號": "0050", "公司簡稱": "衝突"})
    install_http(monkeypatch, values)
    assert service(tmp_path).get_asset("0050") == asset_fallback()


def test_partial_failure_stock_is_medium(monkeypatch, tmp_path):
    values = payloads()
    values[asset_service.TWSE_ETF_URL] = []
    install_http(monkeypatch, values)
    assert service(tmp_path).get_asset("2330") == {
        "type": "stock",
        "source": "twse_company",
        "confidence": "medium",
    }


def test_partial_failure_etf_is_medium(monkeypatch, tmp_path):
    values = payloads()
    values[asset_service.TPEX_COMPANY_URL] = []
    install_http(monkeypatch, values)
    assert service(tmp_path).get_asset("006201") == {
        "type": "etf",
        "source": "tpex_etf",
        "confidence": "medium",
    }


def _empty_source_payloads():
    return {
        asset_service.TWSE_COMPANY_URL: [],
        asset_service.TPEX_COMPANY_URL: [],
        asset_service.TWSE_ETF_URL: [],
        asset_service.TPEX_ETF_URL: {"status": "success", "data": []},
    }


def test_all_empty_sources_preserve_old_cache_as_medium(monkeypatch, tmp_path):
    path = tmp_path / "asset.json"
    original = {
        "updated_at": (NOW - timedelta(hours=25)).isoformat(),
        "sources": {},
        "assets": {"2330": {"type": "stock", "source": "twse_company", "confidence": "high"}},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    install_http(monkeypatch, _empty_source_payloads())
    assert service(tmp_path).get_asset("2330") == {
        "type": "stock",
        "source": "official_cache",
        "confidence": "medium",
    }
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_all_empty_sources_without_cache_are_unknown(monkeypatch, tmp_path):
    install_http(monkeypatch, _empty_source_payloads())
    assert service(tmp_path).get_asset("2330") == asset_fallback()
    assert not (tmp_path / "asset.json").exists()


def test_one_empty_source_is_failed_and_limits_confidence(monkeypatch, tmp_path):
    values = payloads()
    values[asset_service.TWSE_ETF_URL] = []
    install_http(monkeypatch, values)
    result = service(tmp_path).get_asset("2330")
    cache = json.loads((tmp_path / "asset.json").read_text(encoding="utf-8"))
    assert cache["sources"]["twse_etf"]["status"] == "failed"
    assert result["confidence"] == "medium"


def test_partial_valid_partial_empty_uses_only_valid_source(monkeypatch, tmp_path):
    values = _empty_source_payloads()
    values[asset_service.TWSE_COMPANY_URL] = fixture("twse_companies.json")
    install_http(monkeypatch, values)
    result = service(tmp_path).get_asset("2330")
    cache = json.loads((tmp_path / "asset.json").read_text(encoding="utf-8"))
    assert result == {"type": "stock", "source": "twse_company", "confidence": "medium"}
    assert set(cache["assets"]) == {"2303", "2317", "2330", "3481"}
    assert cache["sources"]["twse_company"]["status"] == "ok"
    assert all(cache["sources"][name]["status"] == "failed" for name in asset_service.SOURCE_NAMES if name != "twse_company")


def test_tpex_company_fixture_is_stock(monkeypatch, tmp_path):
    install_http(monkeypatch)
    assert service(tmp_path).get_asset("6488") == {
        "type": "stock",
        "source": "tpex_company",
        "confidence": "high",
    }


@pytest.mark.parametrize(
    "bad_record",
    [
        {"stockName": "missing", "listingDate": "20260101"},
        {"stockNo": 6201, "stockName": "bad", "listingDate": "20260101"},
        {"stockNo": "006201", "stockName": "bad", "listingDate": "20260230"},
    ],
)
def test_tpex_etf_invalid_records_are_ignored(monkeypatch, tmp_path, bad_record):
    values = payloads()
    values[asset_service.TPEX_ETF_URL] = {"status": "success", "data": [bad_record]}
    install_http(monkeypatch, values)
    assert service(tmp_path).get_asset("006201") == asset_fallback()


@pytest.mark.parametrize(
    "bad_payload",
    [None, "bad", {}, {"status": "failed", "data": []}, {"status": "success", "data": {}}],
)
def test_unexpected_tpex_payload_is_safe(monkeypatch, tmp_path, bad_payload):
    values = payloads()
    values[asset_service.TPEX_ETF_URL] = bad_payload
    install_http(monkeypatch, values)
    assert service(tmp_path).get_asset("006201") == asset_fallback()


@pytest.mark.parametrize(
    "failure",
    [Response(status=500), requests.Timeout(), requests.RequestException(), Response(json_error=ValueError())],
)
def test_http_and_json_failures_are_safe(monkeypatch, tmp_path, failure):
    values = {url: failure for url in payloads()}
    calls = install_http(monkeypatch, values)
    assert service(tmp_path).get_asset("2330") == asset_fallback()
    assert len(calls) == 4


def test_cache_miss_refreshes_each_source_once_with_timeout(monkeypatch, tmp_path):
    calls = install_http(monkeypatch)
    result = service(tmp_path).get_asset("2330")
    assert result["type"] == "stock"
    assert calls == [
        ("GET", asset_service.TWSE_COMPANY_URL, 10),
        ("GET", asset_service.TPEX_COMPANY_URL, 10),
        ("GET", asset_service.TWSE_ETF_URL, 10),
        ("POST", asset_service.TPEX_ETF_URL, 10),
    ]


def test_fresh_cache_hit_does_not_call_http(monkeypatch, tmp_path):
    path = tmp_path / "asset.json"
    path.write_text(json.dumps({
        "updated_at": NOW.isoformat(),
        "sources": {},
        "assets": {"2330": {"type": "stock", "source": "twse_company", "confidence": "high"}},
    }), encoding="utf-8")
    monkeypatch.setattr(asset_service.requests, "request", lambda *args, **kwargs: pytest.fail("HTTP called"))
    assert service(tmp_path).get_asset("2330")["source"] == "twse_company"


def test_expired_cache_refresh_success(monkeypatch, tmp_path):
    path = tmp_path / "asset.json"
    path.write_text(json.dumps({"updated_at": (NOW - timedelta(hours=25)).isoformat(), "sources": {}, "assets": {}}), encoding="utf-8")
    install_http(monkeypatch)
    assert service(tmp_path).get_asset("00878")["confidence"] == "high"


def test_written_cache_timestamps_include_taipei_offset(monkeypatch, tmp_path):
    install_http(monkeypatch)
    service(tmp_path).get_asset("2330")
    cache = json.loads((tmp_path / "asset.json").read_text(encoding="utf-8"))
    assert cache["updated_at"].endswith("+08:00")
    assert set(cache["sources"]) == set(asset_service.SOURCE_NAMES)
    assert all(cache["sources"][name]["updated_at"].endswith("+08:00") for name in asset_service.SOURCE_NAMES)


def test_cache_template_has_fixed_source_schema():
    template_path = Path(asset_service.DEFAULT_CACHE_PATH)
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert template["updated_at"] is None
    assert set(template["sources"]) == set(asset_service.SOURCE_NAMES)
    assert all(template["sources"][name] == {"updated_at": None, "status": "unknown"} for name in asset_service.SOURCE_NAMES)
    assert template["assets"] == {}


def test_atomic_write_failure_preserves_old_cache(monkeypatch, tmp_path):
    path = tmp_path / "asset.json"
    original_text = json.dumps({
        "updated_at": (NOW - timedelta(hours=25)).isoformat(),
        "sources": {},
        "assets": {"2330": {"type": "stock", "source": "twse_company", "confidence": "high"}},
    })
    path.write_text(original_text, encoding="utf-8")
    install_http(monkeypatch)
    monkeypatch.setattr(asset_service.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("simulated")))
    service(tmp_path).get_asset("2330")
    assert path.read_text(encoding="utf-8") == original_text
    assert json.loads(path.read_text(encoding="utf-8"))["assets"]["2330"]["type"] == "stock"
    assert list(tmp_path.glob("*.tmp")) == []


def test_expired_cache_all_fail_uses_old_cache_at_medium(monkeypatch, tmp_path):
    path = tmp_path / "asset.json"
    path.write_text(json.dumps({
        "updated_at": (NOW - timedelta(hours=25)).isoformat(),
        "sources": {},
        "assets": {"2330": {"type": "stock", "source": "twse_company", "confidence": "high"}},
    }), encoding="utf-8")
    install_http(monkeypatch, {url: requests.Timeout() for url in payloads()})
    assert service(tmp_path).get_asset("2330") == {
        "type": "stock",
        "source": "official_cache",
        "confidence": "medium",
    }


def test_corrupt_cache_refreshes_safely(monkeypatch, tmp_path):
    (tmp_path / "asset.json").write_text("{broken", encoding="utf-8")
    install_http(monkeypatch)
    assert service(tmp_path).get_asset("006201")["type"] == "etf"


def _mock_market(monkeypatch, no_price=False):
    monkeypatch.setattr(market_service, "get_stock_name", lambda stock_id: "name")
    monkeypatch.setattr(market_service, "get_stock_info", lambda stock_id: None if no_price else {
        "date": "2026-07-12", "close": 100, "open": 99, "max": 101,
        "min": 98, "change": 1, "change_percent": 1, "volume": 1000,
    })
    monkeypatch.setattr(market_service, "get_technical_indicators", lambda stock_id: {"trend": "up"})
    monkeypatch.setattr(market_service.GanzaiAI, "run", lambda self: {"score": 77, "decision": "hold", "confidence": 66})
    monkeypatch.setattr(market_service.FundamentalEngine, "analyze", lambda self, stock_id: {"available": False, "score": 0})
    monkeypatch.setattr(market_service.InstitutionEngine, "analyze", lambda self, stock_id: {"available": False, "score": 0})
    monkeypatch.setattr(market_service.NewsEngine, "analyze", lambda self, stock_id: {"available": False, "score": 0})
    monkeypatch.setattr(market_service.DataQualityEngine, "analyze", lambda self, data: {"status": "ok"})


@pytest.mark.parametrize("no_price", [False, True])
def test_market_service_asset_called_once_in_both_branches(monkeypatch, no_price):
    _mock_market(monkeypatch, no_price)
    calls = []
    monkeypatch.setattr(market_service.AssetService, "get_asset", lambda self, stock_id: calls.append(stock_id) or {"type": "stock", "source": "twse_company", "confidence": "high"})
    result = market_service.get_market_info("2330")
    assert calls == ["2330"]
    assert result["asset"]["type"] == "stock"


@pytest.mark.parametrize("no_price", [False, True])
def test_market_service_asset_exception_does_not_change_other_results(monkeypatch, no_price):
    _mock_market(monkeypatch, no_price)
    monkeypatch.setattr(market_service.AssetService, "get_asset", lambda self, stock_id: (_ for _ in ()).throw(RuntimeError("simulated")))
    result = market_service.get_market_info("2330")
    assert result["asset"] == asset_fallback()
    assert "financial" in result and "institution" in result and "news" in result
    assert "composite" in result and "data_quality" in result
    if not no_price:
        assert result["core"]["score"] == 77
        assert result["core"]["decision"] == "hold"
        assert result["core"]["confidence"] == 66
