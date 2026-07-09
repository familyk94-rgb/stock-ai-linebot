from core.ganzai_ai_v2 import GanzaiAIv2


def test_ganzai_ai_v2():
    stock = {
        "price": 65.3,
        "volume": 380906610,
        "technical": {
            "ma5": 63,
            "ma20": 60,
            "ma60": 55,
            "rsi": 58,
            "k": 60,
            "d": 50,
            "macd": 1,
            "signal": 0,
            "histogram": 1,
        },
    }

    result = GanzaiAIv2(stock).run()

    assert isinstance(result, dict)
    assert "score" in result
    assert "decision" in result
    assert "trend" in result
    assert "ma_signal" in result
    assert "shopkeeper_message" in result