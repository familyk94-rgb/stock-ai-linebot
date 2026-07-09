def build_analysis_card(ai_text):
    return {
        "type": "box",
        "layout": "vertical",
        "margin": "lg",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "🏪 阿柑店長分析",
                "weight": "bold",
                "size": "lg",
                "color": "#111827"
            },
            {
                "type": "text",
                "text": ai_text,
                "wrap": True,
                "size": "sm"
            }
        ]
    }