import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.flex.market_card import _row


_TAIPEI = ZoneInfo("Asia/Taipei")
_PROVIDER_LABELS = {
    "fubon_neo": "富邦 Neo",
    "finmind": "FinMind",
}
_QUALITY_LABELS = {
    "realtime": "即時",
    "delayed": "延遲",
    "stale": "過期",
    "incomplete": "不完整",
    "invalid": "無效",
}
_FORMATTED_TIMESTAMP = re.compile(
    r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$"
)


def build_dashboard_card(
    score: int | float | None = None,
    confidence=None,
    decision: str | None = None,
    risk_level: str | None = None,
    quote=None,
) -> dict:
    score_text = "-" if score is None else str(round(float(score), 1))
    confidence_text = _format_confidence(confidence)

    contents = [
        {
            "type": "text",
            "text": "AI 儀表板",
            "weight": "bold",
            "size": "md",
            "color": "#111827",
        },
        _row("AI 技術分", score_text),
        _row("AI 信心度", confidence_text),
        _row("決策", decision or "觀察"),
        _row("風險", risk_level or "未評估"),
        {
            "type": "separator",
            "margin": "md",
        },
        {
            "type": "text",
            "text": "即時行情",
            "weight": "bold",
            "size": "sm",
            "color": "#111827",
            "margin": "md",
        },
    ]
    contents.extend(_build_quote_rows(quote))

    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "spacing": "sm",
        "contents": contents,
    }


def _format_confidence(value) -> str:
    if isinstance(value, bool):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{round(max(0, min(100, number)))}%"


def _build_quote_rows(quote) -> list[dict]:
    data = quote if isinstance(quote, dict) else {}
    return [
        _row("最新價", _format_number(data.get("price"))),
        _row("漲跌", _format_change(data.get("change"))),
        _row("漲跌幅", _format_change(data.get("change_percent"), suffix="%")),
        _row("成交量", _format_number(data.get("volume"), grouping=True)),
        _row("更新時間", _format_timestamp(data.get("timestamp"))),
        _row("資料來源", _format_provider(data.get("provider"))),
        _row("資料品質", _format_quality(data.get("data_quality"))),
    ]


def _safe_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _format_number(value, *, grouping: bool = False) -> str:
    number = _safe_number(value)
    if number is None:
        return "暫無資料"
    if number.is_integer():
        return format(int(number), "," if grouping else "d")
    return format(number, ",g" if grouping else "g")


def _format_change(value, *, suffix: str = "") -> str:
    number = _safe_number(value)
    if number is None:
        return "暫無資料"
    if number == 0:
        return "—"
    marker = "▲" if number > 0 else "▼"
    return f"{marker} {_format_number(abs(number))}{suffix}"


def _format_provider(value) -> str:
    if not isinstance(value, str):
        return "暫無資料"
    return _PROVIDER_LABELS.get(value.strip().lower(), "暫無資料")


def _format_quality(value) -> str:
    if not isinstance(value, str):
        return "暫無資料"
    return _QUALITY_LABELS.get(value.strip().lower(), "暫無資料")


def _format_timestamp(value) -> str:
    try:
        parsed = _parse_timestamp(value)
    except Exception:
        return "暫無資料"
    if isinstance(parsed, datetime):
        return parsed.astimezone(_TAIPEI).strftime("%Y-%m-%d %H:%M:%S")
    return parsed or "暫無資料"


def _parse_timestamp(value) -> datetime | str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_TAIPEI)
        return value

    if isinstance(value, (int, float)):
        number = _safe_number(value)
        return _timestamp_from_number(number) if number is not None else None

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    number = _safe_number(text)
    if number is not None:
        return _timestamp_from_number(number)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text if _FORMATTED_TIMESTAMP.fullmatch(text) else None
    return parsed.replace(tzinfo=_TAIPEI) if parsed.tzinfo is None else parsed


def _timestamp_from_number(value: float) -> datetime:
    magnitude = abs(value)
    if magnitude >= 100_000_000_000_000:
        value /= 1_000_000
    elif magnitude >= 100_000_000_000:
        value /= 1_000
    return datetime.fromtimestamp(value, tz=timezone.utc)
