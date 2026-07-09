def build_shopkeeper_card(message: str | None = None) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "backgroundColor": "#FEF3C7",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "阿柑店長",
                "weight": "bold",
                "size": "md",
                "color": "#92400E",
            },
            {
                "type": "text",
                "text": message or "目前先觀察，不急著追高。",
                "size": "sm",
                "color": "#78350F",
                "wrap": True,
            },
        ],
    }