from app.flex.design_system import BRAND, TEXT, card


def build_shopkeeper_card(message: str | None = None) -> dict:
    return card(
        [
            {
                "type": "text",
                "text": "🍊 阿柑店長",
                "weight": "bold",
                "size": "lg",
                "color": BRAND,
            },
            {
                "type": "text",
                "text": message or "目前先觀察，不急著追高。",
                "size": "sm",
                "color": TEXT,
                "wrap": True,
            },
        ],
        background="#FFFBEB",
    )
