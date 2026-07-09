def build_analysis_card(summary: str | None = None) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "AI 分析",
                "weight": "bold",
                "size": "md",
                "color": "#111827",
            },
            {
                "type": "text",
                "text": summary or "目前資料不足，建議等待更多訊號。",
                "size": "sm",
                "color": "#374151",
                "wrap": True,
            },
        ],
    }