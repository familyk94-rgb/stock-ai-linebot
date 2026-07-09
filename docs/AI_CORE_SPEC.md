# 股市柑仔店 AI Pro
# AI Core Specification v1.0

Version：v0.2.0
Sprint：Sprint 2
Status：Draft

---

# 1. 目的

AI Core 是整個股市柑仔店 AI Pro 的核心。

所有 AI 判斷皆由 AI Core 完成。

LINE、Web、APP、排行榜、大盤分析、
未來所有功能皆不得自行計算，
只能讀取 AI Core 輸出。

因此 AI Core 是唯一資料來源
(Single Source of Truth)。

---

# 2. AI Core 架構

Market Module
        │
        ▼
GanzaiAI
        │
        ├── Score Engine
        ├── Health Engine
        ├── Consensus Engine
        ├── Risk Engine
        ├── Strategy Engine
        ├── Decision Engine
        ├── Explain Engine
        └── Shopkeeper Engine
        │
        ▼
AI Adapter (OpenAI)
        │
        ▼
Flex / Web / APP

---

# 3. AI Core Output

AI Core 必須永遠輸出固定 JSON。

不得因 Engine 修改而改變格式。

Standard Output：

{
    "score": 0,

    "health": "",

    "decision": "",

    "risk_level": "",

    "trend": "",

    "ma_signal": "",

    "macd_signal": "",

    "rsi_signal": "",

    "strategy": "",

    "shopkeeper_message": "",

    "ai_summary": "",

    "explain": [],

    "_raw": {}
}

---

# 4. Score Engine

目的：

計算 AI Score。

輸出：

{
    "score": 82,
    "star": 4,
    "grade": "A",
    "color": "#22C55E"
}

Score：

90~100
★★★★★

80~89
★★★★☆

70~79
★★★☆☆

60~69
★★☆☆☆

0~59
★☆☆☆☆

---

# 5. Health Engine

目的：

計算股票健康度。

輸出：

{
    "health_score": 84,
    "health_level": "健康"
}

Level：

健康

普通

注意

危險

---

# 6. Consensus Engine

目的：

整合所有技術分析。

輸出：

{
    "trend": "多頭",

    "ma_signal": "站上MA20",

    "macd_signal": "黃金交叉",

    "rsi_signal": "58",

    "kd_signal": "黃金交叉"
}

---

# 7. Risk Engine

目的：

評估風險。

輸出：

{
    "risk_score": 28,

    "risk_level": "中低",

    "reason": [
        "...",
        "..."
    ]
}

Risk：

低

中低

中

中高

高

---

# 8. Strategy Engine

目的：

提供操作策略。

輸出：

{
    "strategy": "等待MA10"
}

Strategy：

買進

分批

等待

減碼

停利

停損

觀望

---

# 9. Decision Engine

目的：

提供 AI 最終決策。

輸出：

{
    "decision": "偏多",

    "confidence": 86
}

Decision：

強烈買進

買進

偏多

觀察

偏空

減碼

賣出

---

# 10. Explain Engine

目的：

產生 AI 判斷依據。

輸出：

{
    "summary": "...",

    "reason": [

        "...",

        "...",

        "..."

    ]
}

---

# 11. Shopkeeper Engine

目的：

產生阿柑店長語氣。

輸出：

{
    "message": "...",

    "emoji": "🍊"
}

例如：

目前偏多。

今天不用急。

等 MA10。

再分批布局。

---

# 12. AI Adapter

OpenAI 不負責：

❌ AI Score

❌ Risk

❌ Decision

GPT 只負責：

✔ 潤飾文字

✔ Summary

✔ Shopkeeper 語氣

不得讓 GPT 決定買賣。

---

# 13. 使用規範

LINE

Web

APP

排行榜

會員

不得自行重新計算。

只能讀 AI Core JSON。

---

# 14. Version

v0.2.0

Sprint 2

AI Core v1.0