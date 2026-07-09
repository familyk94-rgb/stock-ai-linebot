def build_dashboard_card(
    score: int | float | None = None,
    decision: str | None = None,
    risk_level: str | None = None,
) -> dict:
    score_text = "-" if score is None else str(round(float(score), 1))

    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "AI 儀表板",
                "weight": "bold",
                "size": "md",
                "color": "#111827",
            },
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": "總分",
                        "size": "sm",
                        "color": "#6B7280",
                        "flex": 1,
                    },
                    {
                        "type": "text",
                        "text": score_text,
                        "size": "sm",
                        "weight": "bold",
                        "align": "end",
                        "flex": 2,
                    },
                ],
            },
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": "決策",
                        "size": "sm",
                        "color": "#6B7280",
                        "flex": 1,
                    },
                    {
                        "type": "text",
                        "text": decision or "觀察",
                        "size": "sm",
                        "weight": "bold",
                        "align": "end",
                        "flex": 2,
                    },
                ],
            },
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": "風險",
                        "size": "sm",
                        "color": "#6B7280",
                        "flex": 1,
                    },
                    {
                        "type": "text",
                        "text": risk_level or "未評估",
                        "size": "sm",
                        "weight": "bold",
                        "align": "end",
                        "flex": 2,
                    },
                ],
            },
        ],
    }