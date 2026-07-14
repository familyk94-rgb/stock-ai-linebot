import logging
from time import perf_counter

from services.asset_service import AssetService, asset_fallback
from services.stock_service import get_stock_info
from services.technical_service import get_technical_indicators
from services.stock_name_service import get_stock_name
from core.ganzai_ai import GanzaiAI
from core.data_quality import calculate_data_completeness
from core.data_quality_engine import DataQualityEngine, data_quality_fallback
from core.market.fundamental_engine import FundamentalEngine
from core.market.institution_engine import InstitutionEngine
from core.market.news_engine import NewsEngine
from core.market.composite_analysis_engine import (
    CompositeAnalysisEngine,
    composite_fallback,
)
from core.shopkeeper_engine import get_composite_aware_advice
from core.observability import elapsed_ms, log_event


logger = logging.getLogger(__name__)


def format_number(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return "-"


def format_price(value):
    try:
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{float(value):,.2f}"
    except Exception:
        return "-"


def get_market_info(stock_id: str) -> dict:
    started_at = _safe_profile_start()
    stock_id = str(stock_id).strip()
    _safe_event("market_service_start", result="success")
    try:
        market_data = _build_market_info(stock_id)
    except TimeoutError as error:
        _safe_profile_event("market_service_end", result="timeout", started_at=started_at, error_type=type(error).__name__)
        raise
    except Exception as error:
        _safe_profile_event("market_service_end", result="error", started_at=started_at, error_type=type(error).__name__)
        raise
    result = "success" if isinstance(market_data, dict) and market_data.get("price") is not None else "fallback"
    _safe_profile_event("market_service_end", result=result, started_at=started_at)
    return market_data


def _build_market_info(stock_id: str) -> dict:
    fundamental_engine = FundamentalEngine()
    institution_engine = InstitutionEngine()
    news_engine = NewsEngine()
    composite_engine = CompositeAnalysisEngine()
    data_quality_engine = DataQualityEngine()
    asset_service = AssetService()

    stock_name = get_stock_name(stock_id) or ""
    asset = _get_asset(asset_service, stock_id)

    stock = get_stock_info(stock_id)

    if not stock:
        financial = _get_fundamental_analysis(fundamental_engine, stock_id, asset)
        institution = _get_institution_analysis(institution_engine, stock_id)
        news = _get_news_analysis(news_engine, stock_id)
        composite = _get_composite_analysis(
            composite_engine,
            {"available": False, "score": None},
            financial,
            institution,
            news,
        )
        market_data = {
            "stock_id": stock_id,
            "stock_code": stock_id,
            "stock_name": stock_name,
            "date": "-",
            "price": None,
            "open": None,
            "high": None,
            "low": None,
            "change": None,
            "change_percent": None,
            "volume": None,
            "price_text": "-",
            "open_text": "-",
            "high_text": "-",
            "low_text": "-",
            "volume_text": "-",
            "trend": "資料不足",
            "ma_signal": "資料不足",
            "macd_signal": "資料不足",
            "rsi_signal": "資料不足",
            "technical": {},
            "financial": financial,
            "institution": institution,
            "news": news,
            "composite": composite,
            "asset": asset,
            "core": {"data_completeness": 0},
        }
        market_data["data_quality"] = _get_data_quality(data_quality_engine, market_data)
        return market_data

    technical = get_technical_indicators(stock_id) or {}

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

        "price_text": format_price(stock.get("close")),
        "open_text": format_price(stock.get("open")),
        "high_text": format_price(stock.get("max")),
        "low_text": format_price(stock.get("min")),
        "volume_text": format_number(stock.get("volume")),

        "trend": technical.get("trend", "未判定"),
        "ma_signal": technical.get("ma_signal", "未判定"),
        "macd_signal": technical.get("macd_signal", "未判定"),
        "rsi_signal": technical.get("rsi_signal", "未判定"),

        "technical": technical,
        "asset": asset,
    }

    stock_data["core"] = _get_ai_core_analysis(stock_data)

    stock_data["financial"] = _get_fundamental_analysis(
        fundamental_engine,
        stock_id,
        asset,
    )
    stock_data["institution"] = _get_institution_analysis(
        institution_engine,
        stock_id,
    )
    stock_data["news"] = _get_news_analysis(news_engine, stock_id)
    stock_data["composite"] = _get_composite_analysis(
        composite_engine,
        {
            "available": bool(stock_data.get("technical")),
            "score": (stock_data.get("core") or {}).get("score"),
        },
        stock_data["financial"],
        stock_data["institution"],
        stock_data["news"],
    )
    _update_shopkeeper_message(stock_data)
    stock_data["data_quality"] = _get_data_quality(data_quality_engine, stock_data)

    return stock_data


def _get_ai_core_analysis(stock_data: dict) -> dict:
    started_at = _safe_profile_start()
    try:
        result = GanzaiAI(stock_data).run() or {}
    except Exception as error:
        _safe_profile_event("ai_core_analysis_end", result="fallback", started_at=started_at, error_type=type(error).__name__, service="ai_core")
        return {"data_completeness": calculate_data_completeness(stock_data)}
    _safe_profile_event("ai_core_analysis_end", result="success" if result else "fallback", started_at=started_at, service="ai_core")
    return result


def _get_fundamental_analysis(
    engine: FundamentalEngine,
    stock_id: str,
    asset: dict,
) -> dict:
    started_at = _safe_profile_start()
    try:
        result = engine.analyze(stock_id, asset=asset)
    except Exception as error:
        _safe_event("service_fallback", result="fallback", error_type=type(error).__name__, service="fundamental")
        result = _fundamental_fallback(asset)
        _safe_profile_event("fundamental_analysis_end", result="fallback", started_at=started_at, error_type=type(error).__name__, service="fundamental")
        return result
    if isinstance(result, dict) and result.get("applicability") == "not_applicable":
        stage_result = "skipped"
    else:
        stage_result = "success" if isinstance(result, dict) and result.get("available") is True else "fallback"
    _safe_profile_event("fundamental_analysis_end", result=stage_result, started_at=started_at, service="fundamental")
    return result


def _fundamental_fallback(asset: dict | None = None) -> dict:
    is_etf = isinstance(asset, dict) and asset.get("type") == "etf"
    return {
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "dividend_yield": None,
        "score": 0,
        "summary": "ETF 不適用個股基本面" if is_etf else "尚未整合",
        "signals": [],
        "available": False,
        "applicability": "not_applicable" if is_etf else "unknown",
    }


def _get_institution_analysis(engine: InstitutionEngine, stock_id: str) -> dict:
    started_at = _safe_profile_start()
    try:
        result = engine.analyze(stock_id)
    except Exception as error:
        _safe_event("service_fallback", result="fallback", error_type=type(error).__name__, service="institution")
        result = _institution_fallback()
        _safe_profile_event("institution_analysis_end", result="fallback", started_at=started_at, error_type=type(error).__name__, service="institution")
        return result
    stage_result = "success" if isinstance(result, dict) and result.get("available") is True else "fallback"
    _safe_profile_event("institution_analysis_end", result=stage_result, started_at=started_at, service="institution")
    return result


def _institution_fallback() -> dict:
    return {
        "foreign_buy_sell": None,
        "investment_buy_sell": None,
        "dealer_buy_sell": None,
        "three_major_buy_sell": None,
        "foreign_streak": None,
        "investment_streak": None,
        "dealer_streak": None,
        "score": 0,
        "summary": "尚未整合",
        "signals": [],
        "available": False,
    }


def _get_news_analysis(engine: NewsEngine, stock_id: str) -> dict:
    started_at = _safe_profile_start()
    try:
        result = engine.analyze(stock_id)
    except Exception as error:
        _safe_event("service_fallback", result="fallback", error_type=type(error).__name__, service="news")
        result = _news_fallback()
        _safe_profile_event("news_analysis_end", result="fallback", started_at=started_at, error_type=type(error).__name__, service="news")
        return result
    stage_result = "success" if isinstance(result, dict) and result.get("available") is True else "fallback"
    _safe_profile_event("news_analysis_end", result=stage_result, started_at=started_at, service="news")
    return result


def _news_fallback() -> dict:
    return {
        "items": [],
        "count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "neutral_count": 0,
        "score": 0,
        "summary": "尚未整合",
        "signals": [],
        "available": False,
    }


def _get_composite_analysis(
    engine: CompositeAnalysisEngine,
    technical: dict,
    financial: dict,
    institution: dict,
    news: dict,
) -> dict:
    started_at = _safe_profile_start()
    try:
        result = engine.analyze(technical, financial, institution, news)
    except Exception as error:
        _safe_event("service_fallback", result="fallback", error_type=type(error).__name__, service="composite")
        result = composite_fallback()
        _safe_profile_event("composite_analysis_end", result="fallback", started_at=started_at, error_type=type(error).__name__, service="composite")
        return result
    stage_result = "success" if isinstance(result, dict) and result.get("available") is True else "fallback"
    _safe_profile_event("composite_analysis_end", result=stage_result, started_at=started_at, service="composite")
    return result


def _update_shopkeeper_message(market_data: dict) -> None:
    started_at = _safe_profile_start()
    try:
        core = market_data.get("core")
        if not isinstance(core, dict):
            _safe_profile_event("shopkeeper_analysis_end", result="skipped", started_at=started_at, service="shopkeeper")
            return
        current_message = core.get("shopkeeper_message")
        updated_message = get_composite_aware_advice(
            current_message,
            core.get("decision"),
            market_data.get("composite"),
        )
        if isinstance(current_message, str) and updated_message != current_message:
            core["shopkeeper_message"] = updated_message
            result = "success"
        else:
            result = "skipped"
    except Exception as error:
        _safe_profile_event(
            "shopkeeper_analysis_end",
            result="fallback",
            started_at=started_at,
            error_type=type(error).__name__,
            service="shopkeeper",
        )
        return
    _safe_profile_event("shopkeeper_analysis_end", result=result, started_at=started_at, service="shopkeeper")


def _safe_profile_start():
    try:
        return perf_counter()
    except Exception:
        return None


def _safe_profile_event(event: str, *, result: str, started_at=None, **fields) -> None:
    try:
        try:
            elapsed = elapsed_ms(started_at)
        except Exception:
            elapsed = 0
        log_event(logger, event, result=result, elapsed=elapsed, **fields)
    except Exception:
        return


def _safe_event(event: str, *, result: str, **fields) -> None:
    try:
        log_event(logger, event, result=result, **fields)
    except Exception:
        return


def _get_data_quality(engine: DataQualityEngine, market_data: dict) -> dict:
    started_at = _safe_profile_start()
    try:
        result = engine.analyze(market_data)
    except Exception as error:
        _safe_event("service_fallback", result="fallback", error_type=type(error).__name__, service="data_quality")
        result = data_quality_fallback()
        _safe_profile_event("data_quality_analysis_end", result="fallback", started_at=started_at, error_type=type(error).__name__, service="data_quality")
        return result
    stage_result = "success" if isinstance(result, dict) and result.get("status") not in {None, "資料不足"} else "fallback"
    _safe_profile_event("data_quality_analysis_end", result=stage_result, started_at=started_at, service="data_quality")
    return result


def _get_asset(service: AssetService, stock_id: str) -> dict:
    try:
        return service.get_asset(stock_id)
    except Exception as error:
        _safe_event("service_fallback", result="fallback", error_type=type(error).__name__, service="asset")
        return asset_fallback()
