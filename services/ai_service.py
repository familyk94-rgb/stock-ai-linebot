from openai import OpenAI
from app.config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def ai_stock_analysis(stock):
    prompt = f"""
你是一位專業台股分析師。

請根據以下資料，提供簡短分析。

股票名稱：{stock['stock_name']}
股票代號：{stock['stock_id']}
收盤價：{stock['price']}
最高價：{stock['high']}
最低價：{stock['low']}
成交量：{stock['volume_text']}

請使用以下格式：

📊 AI分析
📈 趨勢：
💡 操作建議：
⚠️ 風險提醒：

限制150字內。
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.choices[0].message.content