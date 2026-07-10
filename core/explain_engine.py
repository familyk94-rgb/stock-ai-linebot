def explain_ai_index(stock, analysis):
    ai_index = analysis.get("ai_index") or {}
    details = ai_index.get("details") or {}

    explanations = [
        f"📈 趨勢分數：{details.get('trend', 0)}/25",
        f"🚀 動能分數：{details.get('momentum', 0)}/20",
        f"🌡 強弱分數：{details.get('strength', 0)}/15",
        f"💰 價格位置：{details.get('price', 0)}/15",
        f"📊 成交量：{details.get('volume', 0)}/10",
    ]

    return {
        "score_reason": explanations,
        "summary": _score_summary(details),
    }


def build_analysis_sections(stock: dict) -> dict:
    """建立用途不同的摘要與詳細原因，供既有 Flex 欄位直接顯示。"""
    stock = stock or {}
    core = stock.get("core") or {}
    technical = stock.get("technical") or {}

    trend = core.get("trend") or stock.get("trend") or "未判定"
    decision = core.get("decision") or "觀察"
    confidence = core.get("confidence")
    risk_level = core.get("risk_level") or "未評估"
    action = core.get("decision_action") or decision

    summary = "\n".join(
        [
            "摘要",
            f"趨勢總結：目前趨勢為{trend}，整體判斷為{decision}。",
            f"短線建議：{_short_term_advice(core, technical)}",
            f"中線建議：{_mid_term_advice(stock, core, technical)}",
            f"長線建議：{_long_term_advice(stock)}",
            f"AI信心度：{_format_confidence(confidence)}",
        ]
    )

    details = "\n".join(
        [
            "詳細原因",
            f"技術面：{_technical_reason(core, technical)}",
            f"基本面：{_data_status(stock.get('financial'))}",
            f"籌碼面：{_data_status(stock.get('institution'))}",
            f"市場情緒：{_market_sentiment(core, trend)}",
            f"操作建議：{action}。",
            f"風險提醒：{_risk_warning(core, risk_level)}",
        ]
    )

    return {
        "ai_summary": summary,
        "explain": details,
    }


def _score_summary(details: dict) -> list:
    trend = details.get("trend", 0)
    momentum = details.get("momentum", 0)
    strength = details.get("strength", 0)
    summary = []

    summary.append("均線結構偏多" if trend >= 20 else "均線仍有支撐" if trend >= 10 else "均線結構偏弱")
    summary.append("動能表現偏強" if momentum >= 15 else "動能中性" if momentum >= 8 else "動能偏弱")

    if strength >= 12:
        summary.append("RSI 位於相對健康區")
    elif strength <= 6:
        summary.append("RSI 顯示風險升高")

    return summary


def _short_term_advice(core: dict, technical: dict) -> str:
    rsi = technical.get("rsi")
    kd_signal = core.get("kd_signal")

    if _number(rsi) is not None and _number(rsi) > 70:
        return "指標偏熱，避免追高並留意拉回。"
    if kd_signal in {"死亡交叉", "低檔偏弱"}:
        return "短線動能轉弱，先觀察止跌訊號。"
    return "依目前訊號分批應對，避免一次追價。"


def _mid_term_advice(stock: dict, core: dict, technical: dict) -> str:
    price = _number(stock.get("price"))
    ma20 = _number(technical.get("ma20"))
    ma60 = _number(technical.get("ma60"))

    if price is not None and ma20 is not None and price < ma20:
        return "尚未站回 MA20 前以保守觀察為主。"
    if ma20 is not None and ma60 is not None and ma20 >= ma60:
        return "中期均線結構尚可，可觀察回檔支撐。"
    return f"依「{core.get('decision', '觀察')}」方向持續追蹤趨勢。"


def _long_term_advice(stock: dict) -> str:
    if not stock.get("financial"):
        return "基本面資料尚未整合，暫不做長線定論。"
    return "需持續追蹤基本面變化，不宜只依技術訊號決策。"


def _technical_reason(core: dict, technical: dict) -> str:
    indicators = [
        ("均線", core.get("ma_signal") or "未判定"),
        ("MACD", core.get("macd_signal") or "未判定"),
        ("RSI", core.get("rsi_signal") or "未判定"),
        ("KD", core.get("kd_signal") or "未判定"),
    ]
    formatted = [
        f"{indicator}：{_dedupe_indicator_signal(signal)}"
        for indicator, signal in indicators
    ]
    return "、".join(formatted) + "。"


def _dedupe_indicator_signal(signal) -> str:
    if isinstance(signal, (list, tuple)):
        parts = [str(item).strip() for item in signal]
    else:
        parts = [item.strip() for item in str(signal).split("、")]
    unique_parts = list(dict.fromkeys(item for item in parts if item))
    return "、".join(unique_parts) or "未判定"


def _market_sentiment(core: dict, trend: str) -> str:
    consensus = core.get("consensus_score")
    if consensus is None:
        return f"目前以技術共識判斷為{trend}，尚無獨立情緒資料。"
    return f"技術指標共識度為 {consensus}%，目前偏向{trend}；尚無獨立情緒資料。"


def _risk_warning(core: dict, risk_level: str) -> str:
    risk_score = core.get("risk_score")
    raw_risk = (core.get("_raw") or {}).get("risk") or {}
    reports = raw_risk.get("reports") or []
    reason = reports[0] if reports else "仍應設定停損並控制部位"

    if risk_score is None:
        return f"目前為{risk_level}；{reason}。"
    return f"風險分數 {risk_score}，等級為{risk_level}；{reason}。"


def _data_status(data) -> str:
    return "已有資料，建議搭配趨勢持續追蹤。" if data else "尚未整合"


def _format_confidence(confidence) -> str:
    value = _number(confidence)
    return "尚未評估" if value is None else f"{value:g}%"


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
