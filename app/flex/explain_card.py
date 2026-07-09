def build_explain_card(stock):
    core = stock.get("core") or {}
    explain = core.get("explain") or {}

    score_reason = explain.get("score_reason") or []
    summary = explain.get("summary") or []

    reason_text = "\n".join(score_reason)
    summary_text = "\n".join([f"• {item}" for item in summary])

    return {
        "type": "box",
        "layout": "vertical",
        "margin": "lg",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "🧠 AI 解釋",
                "weight": "bold",
                "size": "lg"
            },
            {
                "type": "text",
                "text": reason_text,
                "size": "sm",
                "wrap": True
            },
            {
                "type": "text",
                "text": summary_text,
                "size": "sm",
                "wrap": True,
                "margin": "md"
            }
        ]
    }