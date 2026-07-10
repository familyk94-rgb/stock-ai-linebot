import math


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
            f"技術面：\n\n{_technical_reason(core, technical)}",
            _fundamental_section(stock.get("financial")),
            _institution_section(stock.get("institution")),
            f"市場情緒：\n\n{_market_sentiment(core, trend)}",
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
    financial = stock.get("financial") or {}
    if not financial.get("available"):
        return "基本面資料尚未整合，暫不做長線定論。"
    return "需持續追蹤基本面變化，不宜只依技術訊號決策。"


def _technical_reason(core: dict, technical: dict) -> str:
    return "\n\n".join(_format_technical_signals(core))


def _format_technical_signals(core: dict) -> list[str]:
    ma_signal = _dedupe_indicator_signal(core.get("ma_signal") or "未判定")
    macd_signal = _dedupe_indicator_signal(core.get("macd_signal") or "未判定")
    rsi_signal = _dedupe_indicator_signal(core.get("rsi_signal") or "未判定")
    kd_signal = _dedupe_indicator_signal(core.get("kd_signal") or "未判定")

    lines = [f"均線：\n{ma_signal}"]
    if macd_signal == kd_signal and macd_signal in {"死亡交叉", "黃金交叉"}:
        lines.append(f"動能：\nMACD、KD {macd_signal}")
    else:
        lines.extend(
            [
                f"MACD：\n{macd_signal}",
                f"KD：\n{kd_signal}",
            ]
        )
    lines.append(f"RSI：\n{rsi_signal}")
    return lines


def _dedupe_indicator_signal(signal) -> str:
    if isinstance(signal, (list, tuple)):
        parts = [str(item).strip() for item in signal]
    else:
        parts = [item.strip() for item in str(signal).split("、")]
    unique_parts = list(dict.fromkeys(item for item in parts if item))
    return "、".join(unique_parts) or "未判定"


def _market_sentiment(core: dict, trend: str) -> str:
    consensus = core.get("consensus_score")
    consensus_text = "尚未評估" if consensus is None else f"{consensus}%"
    return (
        f"技術指標共識度：\n\n{consensus_text}\n\n"
        f"目前偏向：\n\n{_sentiment_bias(trend)}\n\n"
        "新聞：\n\n尚未整合"
    )


def _sentiment_bias(trend: str) -> str:
    if "多" in str(trend):
        return "偏多"
    if "空" in str(trend):
        return "偏空"
    if trend in {None, "", "未判定", "資料不足"}:
        return "中性"
    return str(trend)


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


def _fundamental_section(financial) -> str:
    if not isinstance(financial, dict) or not financial.get("available"):
        return "基本面：尚未整合"

    fields = [
        ("EPS", "eps", 2, ""),
        ("本益比(PER)", "pe", 1, ""),
        ("股價淨值比(PBR)", "pb", 1, ""),
        ("殖利率", "dividend_yield", 1, "%"),
        ("月營收 YoY", "revenue_growth", 1, "%"),
    ]
    lines = []
    for label, key, decimals, suffix in fields:
        value = _finite_number(financial.get(key))
        if value is not None:
            lines.append(f"{label}：{value:.{decimals}f}{suffix}")

    summary = str(financial.get("summary") or "尚未整合")
    lines.append(f"AI判定：{summary}")
    return "基本面：\n\n" + "\n\n".join(
        line.replace("：", "：\n", 1) for line in lines
    )


def _institution_section(institution) -> str:
    if not isinstance(institution, dict) or not institution.get("available"):
        return "籌碼面：尚未整合"

    fields = [
        ("外資", "foreign_buy_sell"),
        ("投信", "investment_buy_sell"),
        ("自營商", "dealer_buy_sell"),
        ("三大法人", "three_major_buy_sell"),
    ]
    lines = []
    for label, key in fields:
        value = _finite_number(institution.get(key))
        if value is not None:
            value_text = _format_buy_sell(value)
            if label == "三大法人" and value != 0:
                value_text = f"合計{value_text}"
            lines.append(f"{label}：\n{value_text}")

    summary = str(institution.get("summary") or "尚未整合")
    lines.append(f"AI判定：\n{summary}")
    return "籌碼面：\n\n" + "\n\n".join(lines)


def _format_buy_sell(value: float) -> str:
    if value == 0:
        return "持平"
    amount = abs(value)
    amount_text = f"{int(amount):,}" if amount.is_integer() else f"{amount:,.2f}"
    action = "買超" if value > 0 else "賣超"
    return f"{action} {amount_text} 張"


def _format_confidence(confidence) -> str:
    value = _number(confidence)
    return "尚未評估" if value is None else f"{value:g}%"


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _finite_number(value):
    number = _number(value)
    return number if number is not None and math.isfinite(number) else None
