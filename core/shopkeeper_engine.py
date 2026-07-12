import math


def get_shopkeeper_advice(ai_score, risk_score):
    """
    阿柑店長建議 V1.0
    依照 AI 指數與風險分數，產生固定且一致的店長建議。
    """

    if ai_score >= 90:
        advice = {
            "level": "S",
            "title": "🟣 可優先研究",
            "message": "我會把這檔列入優先研究名單，但還是會分批布局，不會一次重押。",
            "tip": "今天重點不是追高，而是挑選好股票。",
        }

    elif ai_score >= 80:
        advice = {
            "level": "A+",
            "title": "🟢 偏多布局",
            "message": "我會偏多看待這檔，但會採分批布局，避免一次買滿。",
            "tip": "好的股票，通常值得耐心布局。",
        }

    elif ai_score >= 70:
        advice = {
            "level": "A",
            "title": "🔵 持續追蹤",
            "message": "我會持續追蹤這檔，等進場訊號更明確再出手。",
            "tip": "耐心，是投資最重要的能力。",
        }

    elif ai_score >= 60:
        advice = {
            "level": "B",
            "title": "🟡 觀察為主",
            "message": "我會先觀察，不急著追價，等多空方向更清楚。",
            "tip": "等待，比亂買更重要。",
        }

    elif ai_score >= 40:
        advice = {
            "level": "C",
            "title": "🟠 保守觀望",
            "message": "目前結構偏弱，我會先保留資金，等待更好的機會。",
            "tip": "保留現金，也是投資策略。",
        }

    else:
        advice = {
            "level": "D",
            "title": "🔴 避免介入",
            "message": "目前風險偏高，我不會急著進場。",
            "tip": "市場每天都有機會，不急於今天。",
        }

    # 風險修正
    if risk_score >= 70:
        advice["title"] = "🔴 高風險警戒"
        advice["message"] = "雖然 AI 指數有參考價值，但目前風險偏高，我會先降低部位或觀望。"
        advice["tip"] = "風險高的時候，活下來比賺快錢更重要。"

    elif risk_score >= 50 and ai_score >= 70:
        advice["message"] += " 不過風險已經升高，我會降低部位，不會重押。"
        advice["tip"] = "分批、控風險，比一次猜方向更重要。"

    return advice


def get_composite_aware_advice(current_message, decision, composite) -> str:
    """依既有決策與綜合分析微調店長文案，不改變任何分析結果。"""
    original = current_message if isinstance(current_message, str) else ""
    try:
        if not isinstance(composite, dict) or composite.get("available") is not True:
            return original
        if not {"score", "summary", "coverage"}.issubset(composite):
            return original

        score = composite.get("score")
        coverage = composite.get("coverage")
        if not _finite_number(score) or not _finite_number(coverage):
            return original

        if decision in {"強烈買進", "買進", "偏多"}:
            if score >= 60:
                message = "目前技術與整體訊號偏多，可分批觀察，仍需留意風險。"
            elif score < 40:
                message = "技術面偏多，但整體訊號仍偏弱，先觀察，不宜追高。"
            else:
                message = _append_sentence(original, "整體訊號偏中性，等待方向明確。")
        elif decision in {"偏空", "減碼", "賣出"}:
            if score >= 60:
                message = "基本面或籌碼面可能較佳，但技術面仍弱，等待止跌訊號。"
            elif score < 40:
                message = "技術與整體訊號皆偏弱，先保守觀望。"
            else:
                message = _append_sentence(original, "整體訊號偏中性，等待方向明確。")
        else:
            return original

        if coverage < 50:
            message = _append_sentence(message, "目前分析面向不足，判斷需保守。")
        return message
    except Exception:
        return original


def _finite_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _append_sentence(message: str, sentence: str) -> str:
    if not message:
        return sentence
    separator = "" if message.endswith(("。", "！", "？")) else "。"
    return f"{message}{separator}{sentence}"
