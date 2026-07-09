def build_header(stock):
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": "#111827",
        "paddingAll": "20px",
        "contents": [
            {
                "type": "text",
                "text": "🏪 股市柑仔店 AI Pro",
                "weight": "bold",
                "color": "#FBBF24",
                "size": "md"
            },
            {
                "type": "text",
                "text": f"{stock['stock_name']}（{stock['stock_id']}）",
                "weight": "bold",
                "size": "xxl",
                "color": "#FFFFFF",
                "margin": "lg"
            },
            {
                "type": "text",
                "text": f"資料日期：{stock['date']}",
                "size": "sm",
                "color": "#D1D5DB",
                "margin": "md"
            }
        ]
    }