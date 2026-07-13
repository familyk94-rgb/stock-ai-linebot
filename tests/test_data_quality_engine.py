from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core import data_quality_engine
from core.data_quality_engine import DataQualityEngine


NOW = datetime(2026, 7, 12, 12, 30, tzinfo=ZoneInfo("Asia/Taipei"))


@pytest.fixture(autouse=True)
def fixed_taipei_now(monkeypatch):
    monkeypatch.setattr(data_quality_engine, "_taipei_now", lambda: NOW)


def market(**overrides):
    data = {
        "date": "2026-07-11",
        "price": 1000,
        "technical": {"trend": "多頭"},
        "financial": {"available": True},
        "institution": {"available": True, "date": "2026-07-11"},
        "news": {
            "available": True,
            "items": [{"date": "2026-07-12", "title": "新聞"}],
        },
        "core": {"score": 80, "decision": "偏多", "confidence": 70},
    }
    data.update(overrides)
    return data


def analyze(value):
    return DataQualityEngine().analyze(value)


def test_all_sources_available_is_normal_and_complete_without_mutation():
    data = market()
    original = deepcopy(data)
    result = analyze(data)
    assert result["status"] == "正常"
    assert result["data_completeness"] == 100
    assert result["available_sources"] == [
        "price", "technical", "fundamental", "institution", "news"
    ]
    assert result["missing_sources"] == []
    assert data == original


def test_four_sources_available_is_normal():
    result = analyze(market(financial={"available": False}))
    assert result["status"] == "正常"
    assert result["data_completeness"] == 80


def test_etf_fundamental_is_not_applicable_and_full_coverage_is_complete():
    result = analyze(
        market(
            financial={
                "available": False,
                "applicability": "not_applicable",
            }
        )
    )
    assert result["status"] == "正常"
    assert result["data_completeness"] == 100
    assert result["not_applicable_sources"] == ["fundamental"]
    assert "fundamental" not in result["available_sources"]
    assert "fundamental" not in result["missing_sources"]
    assert result["source_dates"]["fundamental"] is None


def test_etf_three_of_four_applicable_sources_is_seventy_five_percent():
    result = analyze(
        market(
            financial={"available": False, "applicability": "not_applicable"},
            institution={"available": False},
        )
    )
    assert result["data_completeness"] == 75
    assert result["missing_sources"] == ["institution"]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {
                "institution": {"available": False},
                "news": {"available": False},
            },
            50,
        ),
        (
            {
                "technical": {},
                "institution": {"available": False},
                "news": {"available": False},
            },
            25,
        ),
        (
            {
                "date": None,
                "price": None,
                "technical": {},
                "institution": {"available": False},
                "news": {"available": False},
            },
            0,
        ),
    ],
)
def test_etf_completeness_boundaries(overrides, expected):
    result = analyze(
        market(
            financial={"available": False, "applicability": "not_applicable"},
            **overrides,
        )
    )
    assert result["data_completeness"] == expected
    if expected in {25, 0}:
        assert result["status"] == "資料不足"


def test_etf_source_sets_are_disjoint_unique_and_exhaustive():
    result = analyze(
        market(
            financial={"available": False, "applicability": "not_applicable"},
            institution={"available": False},
        )
    )
    groups = [
        result["available_sources"],
        result["missing_sources"],
        result["not_applicable_sources"],
    ]
    assert all(len(group) == len(set(group)) for group in groups)
    assert set(groups[0]).isdisjoint(groups[1])
    assert set(groups[0]).isdisjoint(groups[2])
    assert set(groups[1]).isdisjoint(groups[2])
    assert set().union(*(set(group) for group in groups)) == {
        "price", "technical", "fundamental", "institution", "news"
    }
    assert result["not_applicable_sources"] == ["fundamental"]
    assert "fundamental" not in result["available_sources"]
    assert "fundamental" not in result["missing_sources"]


def test_unknown_fundamental_remains_missing_with_stock_denominator():
    result = analyze(
        market(financial={"available": False, "applicability": "unknown"})
    )
    assert result["data_completeness"] == 80
    assert result["not_applicable_sources"] == []
    assert "fundamental" in result["missing_sources"]


def test_explicit_technical_available_flag_without_values_is_not_enough():
    result = analyze(market(technical={"available": True}))
    assert "technical" in result["missing_sources"]
    assert result["source_dates"]["technical"] is None


def test_three_sources_is_partial_and_sixty_percent():
    result = analyze(market(financial={}, institution={}))
    assert result["status"] == "部分資料"
    assert result["data_completeness"] == 60


def test_one_source_is_insufficient_and_twenty_percent():
    result = analyze(
        market(technical={}, financial={}, institution={}, news={})
    )
    assert result["status"] == "資料不足"
    assert result["data_completeness"] == 20


def test_missing_price_is_insufficient_even_with_other_sources():
    result = analyze(market(price=None))
    assert result["status"] == "資料不足"
    assert "price" in result["missing_sources"]


@pytest.mark.parametrize(
    ("overrides", "source"),
    [
        ({"date": "2026-07-07"}, "price"),
        ({"institution": {"available": True, "date": "2026-07-04"}}, "institution"),
        ({"news": {"available": True, "items": [{"date": "2026-07-04"}]}}, "news"),
    ],
)
def test_stale_dated_source_marks_partial(overrides, source):
    result = analyze(market(**overrides))
    assert result["is_stale"] is True
    assert result["status"] == "部分資料"
    assert result["source_dates"][source] is not None


@pytest.mark.parametrize(
    ("overrides", "source"),
    [
        ({"date": "2026-07-08"}, "price"),
        ({"institution": {"available": True, "date": "2026-07-05"}}, "institution"),
        ({"news": {"available": True, "items": [{"date": "2026-07-05"}]}}, "news"),
    ],
)
def test_exact_freshness_boundaries_are_not_stale(overrides, source):
    result = analyze(market(**overrides))
    assert result["is_stale"] is False
    assert result["source_dates"][source] is not None


def test_technical_exact_four_days_is_not_stale():
    result = analyze(market(date="2026-07-08", technical={"trend": "多頭"}))
    assert result["source_dates"]["technical"] == "2026-07-08"
    assert result["is_stale"] is False


def test_technical_over_four_days_is_stale():
    result = analyze(market(date="2026-07-07", technical={"trend": "多頭"}))
    assert result["source_dates"]["technical"] == "2026-07-07"
    assert result["is_stale"] is True


def test_fundamental_without_date_is_available_and_not_stale():
    result = analyze(market(financial={"available": True}))
    assert result["source_dates"]["fundamental"] is None
    assert result["is_stale"] is False


def test_all_dates_missing_is_safe():
    result = analyze(
        market(
            date=None,
            price=None,
            technical={"trend": "多頭"},
            financial={"available": True},
            institution={"available": True},
            news={"available": True, "items": []},
        )
    )
    assert result["as_of_date"] is None
    assert result["status"] == "資料不足"


@pytest.mark.parametrize("invalid_date", ["", "invalid", datetime(2026, 7, 11)])
def test_invalid_price_date_inputs_are_safely_ignored(invalid_date):
    result = analyze(market(date=invalid_date))
    assert result["source_dates"]["price"] is None
    assert result["status"] == "資料不足"


def test_future_dates_are_ignored_and_never_become_as_of_date():
    result = analyze(
        market(
            date="2026-07-13",
            technical={"trend": "多頭", "date": "2026-07-13"},
            financial={"available": True, "date": "2026-07-14"},
            institution={"available": True, "date": "2026-07-15"},
            news={"available": True, "items": [{"date": "2026-07-16"}]},
        )
    )
    assert all(value is None for value in result["source_dates"].values())
    assert result["as_of_date"] is None
    assert result["is_stale"] is False


@pytest.mark.parametrize(
    "value",
    [None, "", float("nan"), float("inf"), [], {}, "未判定", "資料不足"],
)
def test_invalid_technical_values_are_not_available(value):
    result = analyze(market(technical={"trend": value}))
    assert "technical" in result["missing_sources"]


@pytest.mark.parametrize(
    "value",
    [50, 50.5, "多頭", "站上 MA20"],
)
def test_valid_technical_values_are_available(value):
    result = analyze(market(technical={"trend": value}))
    assert "technical" in result["available_sources"]


def test_fetched_at_has_taipei_offset_and_as_of_uses_latest_date():
    result = analyze(market())
    assert result["fetched_at"] == "2026-07-12T12:30:00+08:00"
    assert result["as_of_date"] == "2026-07-12"


def test_source_dates_have_fixed_keys_and_completeness_steps():
    result = analyze(market())
    assert list(result["source_dates"]) == [
        "price", "technical", "fundamental", "institution", "news"
    ]
    assert result["data_completeness"] in {0, 20, 40, 60, 80, 100}
    assert result["source_dates"]["technical"] == result["source_dates"]["price"]


def test_source_sets_are_unique_disjoint_and_exhaustive():
    result = analyze(market(financial={}, institution={}))
    available = result["available_sources"]
    missing = result["missing_sources"]
    assert len(available) == len(set(available))
    assert len(missing) == len(set(missing))
    assert set(available).isdisjoint(missing)
    assert set(available) | set(missing) == {
        "price", "technical", "fundamental", "institution", "news"
    }


def test_unavailable_old_institution_and_news_do_not_trigger_stale():
    result = analyze(
        market(
            institution={"available": False, "date": "2020-01-01"},
            news={"available": False, "items": [{"date": "2020-01-01"}]},
        )
    )
    assert result["is_stale"] is False


def test_engine_exception_returns_fixed_fallback(monkeypatch):
    monkeypatch.setattr(
        data_quality_engine,
        "_analyze",
        lambda *args: (_ for _ in ()).throw(RuntimeError("simulated")),
    )
    result = analyze(market())
    assert result["status"] == "資料不足"
    assert result["data_completeness"] == 0
    assert result["available_sources"] == []
    assert set(result["missing_sources"]) == set(result["source_dates"])


def test_timezone_failure_returns_fallback_without_calling_timezone_again(monkeypatch):
    calls = 0

    def fail():
        nonlocal calls
        calls += 1
        raise RuntimeError("timezone unavailable")

    monkeypatch.setattr(data_quality_engine, "_taipei_now", fail)
    result = analyze(market())
    assert calls == 1
    assert result["status"] == "資料不足"
    assert result["fetched_at"] is None
    assert result["source_dates"] == {
        "price": None,
        "technical": None,
        "fundamental": None,
        "institution": None,
        "news": None,
    }


def test_quality_does_not_change_core_analysis_values():
    data = market()
    original_core = deepcopy(data["core"])
    analyze(data)
    assert data["core"] == original_core
