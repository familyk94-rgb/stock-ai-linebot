def get_ai_grade(score):
    if score >= 90:
        return "🟣 S級"
    if score >= 80:
        return "🟢 A+級"
    if score >= 70:
        return "🔵 A級"
    if score >= 60:
        return "🟡 B級"
    if score >= 40:
        return "🟠 C級"
    return "🔴 D級"


def get_progress_bar(value, total=100, length=10):
    try:
        filled = int((value / total) * length)
        filled = max(0, min(filled, length))
        return "█" * filled + "░" * (length - filled)
    except Exception:
        return "░" * length


def build_dashboard_card(stock):
    core = stock.get("core") or {}

    ai = core.get("ai_index") or {}
    health = core.get("health") or {}
    consensus = core.get("consensus") or {}
    risk = core.get("risk") or {}

    ai_score = ai.get("score", 0)
    health_score = health.get("health_score", 0)
    consensus_score = consensus.get("consensus_score", 0)
    risk_score = risk.get("risk_score", 0)

    return {
        "type": "box",
        "layout": "vertical",
        "margin": "lg",
        "spacing": "md",
        "contents": [
            {
                "type": "text",
                "text": "⭐ 股市柑仔店 AI 指數™",
                "weight": "bold",
                "size": "lg",
                "color": "#2563EB"
            },
            {
                "type": "text",
                "text": f"{ai_score} 分　{get_ai_grade(ai_score)}",
                "weight": "bold",
                "size": "xxl",
                "color": "#111827"
            },
            {
                "type": "text",
                "text": ai.get("stars", ""),
                "size": "md",
                "color": "#F59E0B"
            },
            {
                "type": "text",
                "text": ai.get("signal", ""),
                "size": "sm",
                "wrap": True
            },
            {
                "type": "separator",
                "margin": "lg"
            },
            {
                "type": "text",
                "text": f"❤️ AI健康度™：{health_score}",
                "weight": "bold",
                "size": "sm"
            },
            {
                "type": "text",
                "text": get_progress_bar(health_score),
                "size": "sm",
                "color": "#10B981"
            },
            {
                "type": "text",
                "text": health.get("health_level", ""),
                "size": "xs",
                "color": "#10B981",
                "wrap": True
            },
            {
                "type": "text",
                "text": f"🎯 AI共識度™：{consensus_score}%",
                "weight": "bold",
                "size": "sm",
                "margin": "md"
            },
            {
                "type": "text",
                "text": consensus.get("consensus_level", ""),
                "size": "xs",
                "color": "#8B5CF6",
                "wrap": True
            },
            {
                "type": "text",
                "text": f"⚠ AI風險™：{risk_score}",
                "weight": "bold",
                "size": "sm",
                "margin": "md"
            },
            {
                "type": "text",
                "text": get_progress_bar(risk_score),
                "size": "sm",
                "color": "#EF4444"
            },
            {
                "type": "text",
                "text": risk.get("risk_level", ""),
                "size": "xs",
                "color": "#EF4444",
                "wrap": True
            }
        ]
    }