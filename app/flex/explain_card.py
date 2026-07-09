def build_explain_card(explain: str | None = None) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "分析原因",
                "weight": "bold",
                "size": "md",
                "color": "#111827",
            },
            {
                "type": "text",
                "text": explain or "尚未產生完整解釋。",
                "size": "sm",
                "color": "#374151",
                "wrap": True,
            },
        ],
    }