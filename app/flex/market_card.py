def build_market_card(stock):

    return {
        "type": "box",
        "layout": "vertical",
        "margin": "lg",
        "spacing": "sm",
        "contents": [

            {
                "type": "text",
                "text": "💰 即時行情",
                "weight": "bold",
                "size": "lg"
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {
                        "type": "text",
                        "text": "收盤",
                        "size": "sm",
                        "color": "#6B7280",
                        "flex": 2
                    },
                    {
                        "type": "text",
                        "text": stock["price_text"],
                        "size": "sm",
                        "align": "end",
                        "flex": 3
                    }
                ]
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {
                        "type": "text",
                        "text": "開盤",
                        "size": "sm",
                        "color": "#6B7280",
                        "flex": 2
                    },
                    {
                        "type": "text",
                        "text": stock["open_text"],
                        "size": "sm",
                        "align": "end",
                        "flex": 3
                    }
                ]
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {
                        "type": "text",
                        "text": "最高",
                        "size": "sm",
                        "color": "#6B7280",
                        "flex": 2
                    },
                    {
                        "type": "text",
                        "text": stock["high_text"],
                        "size": "sm",
                        "align": "end",
                        "flex": 3
                    }
                ]
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {
                        "type": "text",
                        "text": "最低",
                        "size": "sm",
                        "color": "#6B7280",
                        "flex": 2
                    },
                    {
                        "type": "text",
                        "text": stock["low_text"],
                        "size": "sm",
                        "align": "end",
                        "flex": 3
                    }
                ]
            },

            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {
                        "type": "text",
                        "text": "成交量",
                        "size": "sm",
                        "color": "#6B7280",
                        "flex": 2
                    },
                    {
                        "type": "text",
                        "text": stock["volume_text"],
                        "size": "sm",
                        "align": "end",
                        "flex": 3
                    }
                ]
            }

        ]
    }