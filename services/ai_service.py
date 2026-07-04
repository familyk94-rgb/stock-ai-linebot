import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


def analyze_stock(stock_data: dict):

    prompt = f"""
你是一位專業台股分析師。

請分析下面股票資料：

股票代號：{stock_data['stock_id']}
日期：{stock_data['date']}
收盤價：{stock_data['close']}
最高價：{stock_data['max']}
最低價：{stock_data['min']}
成交量：{stock_data['volume']}

請用繁體中文回答：

1. 今日盤勢
2. 短線分析
3. 操作建議

回答控制在150字內。
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