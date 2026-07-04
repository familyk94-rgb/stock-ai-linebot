from openai import OpenAI
from app.config import OPENAI_API_KEY
from services.cache_service import get_cache, set_cache

client = OpenAI(api_key=OPENAI_API_KEY)


def ai_stock_analysis(stock):
    cache_key = f"ai_analysis_{stock['stock_id']}"

    cached_result = get_cache(cache_key)

    if cached_result:
        return cached_result

    prompt = f"""
你是「股市柑仔店 AI 投資助理」，請用繁體中文分析台股。

股票名稱：{stock['stock_name']}
股票代號：{stock['stock_id']}
日期：{stock['date']}
收盤價：{stock['price_text']} 元
開盤價：{stock['open_text']} 元
最高價：{stock['high_text']} 元
最低價：{stock['low_text']} 元
成交量：{stock['volume_text']}

請用以下格式回答，不要超過 220 字：

🤖 AI 分析
📈 趨勢：
💡 操作建議：
⚠️ 風險提醒：
⭐ AI 信心分數：__ / 100

請避免保證獲利。
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
        )

        ai_text = response.choices[0].message.content

        set_cache(cache_key, ai_text)

        return ai_text

    except Exception as e:
        print(f"AI 分析錯誤：{e}")
        return "🤖 AI 分析暫時無法使用，請稍後再試。"