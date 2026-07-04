from openai import OpenAI
from app.config import OPENAI_API_KEY
from services.cache_service import get_cache, set_cache

client = OpenAI(api_key=OPENAI_API_KEY)


def ai_stock_analysis(stock):
    technical = stock.get("technical") or {}

    cache_key = f"ai_dashboard_{stock['stock_id']}_{stock['date']}"
    cached = get_cache(cache_key)

    if cached:
        return cached

    prompt = f"""
你是「股市柑仔店 AI 投資助理」，請用繁體中文分析台股。

股票名稱：{stock['stock_name']}
股票代號：{stock['stock_id']}
日期：{stock['date']}

價格資料：
收盤價：{stock['price_text']} 元
開盤價：{stock['open_text']} 元
最高價：{stock['high_text']} 元
最低價：{stock['low_text']} 元
成交量：{stock['volume_text']}

技術指標：
MA5：{technical.get('ma5')}
MA10：{technical.get('ma10')}
MA20：{technical.get('ma20')}
MA60：{technical.get('ma60')}
RSI：{technical.get('rsi')}
K：{technical.get('k')}
D：{technical.get('d')}
MACD：{technical.get('macd')}
Signal：{technical.get('signal')}
Histogram：{technical.get('histogram')}

請用以下格式回答，不要超過 260 字：

🤖 AI 分析
📈 趨勢：
📊 技術面：
💡 操作建議：
⚠️ 風險提醒：
⭐ AI 信心分數：__ / 100

請不要保證獲利。
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )

        ai_text = response.choices[0].message.content
        set_cache(cache_key, ai_text)

        return ai_text

    except Exception as e:
        print(f"AI 分析錯誤：{e}")
        return "🤖 AI 分析暫時無法使用，請稍後再試。"