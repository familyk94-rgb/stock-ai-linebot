from core.explain_engine import build_analysis_sections


def _explain(financial: dict) -> str:
    return build_analysis_sections({"financial": financial})["explain"]


def test_unavailable_fundamental_remains_unintegrated():
    explain = _explain({"available": False})

    assert "基本面：尚未整合" in explain
    assert "AI判定：" not in explain


def test_fundamental_with_only_eps():
    explain = _explain(
        {
            "available": True,
            "eps": 5.256,
            "summary": "基本面中性",
        }
    )

    assert "EPS：\n5.26" in explain
    assert "本益比(PER)：" not in explain
    assert "AI判定：\n基本面中性" in explain


def test_fundamental_with_only_per():
    explain = _explain(
        {
            "available": True,
            "pe": 18.26,
            "summary": "基本面中性",
        }
    )

    assert "本益比(PER)：\n18.3" in explain
    assert "EPS：" not in explain


def test_all_fundamental_values_are_formatted_in_order():
    explain = _explain(
        {
            "available": True,
            "eps": 5.256,
            "pe": 18.26,
            "pb": 2.54,
            "dividend_yield": 3.24,
            "revenue_growth": 12.56,
            "summary": "基本面偏佳",
        }
    )

    expected = (
        "基本面：\n\n"
        "EPS：\n5.26\n\n"
        "本益比(PER)：\n18.3\n\n"
        "股價淨值比(PBR)：\n2.5\n\n"
        "殖利率：\n3.2%\n\n"
        "月營收 YoY：\n12.6%\n\n"
        "AI判定：\n基本面偏佳"
    )
    assert expected in explain


def test_none_fundamental_values_are_omitted():
    explain = _explain(
        {
            "available": True,
            "eps": None,
            "pe": 20,
            "pb": None,
            "dividend_yield": 2,
            "revenue_growth": None,
            "summary": "基本面偏弱",
        }
    )

    assert "EPS：" not in explain
    assert "本益比(PER)：\n20.0" in explain
    assert "股價淨值比(PBR)：" not in explain
    assert "殖利率：\n2.0%" in explain
    assert "月營收YoY：" not in explain
    assert "AI判定：\n基本面偏弱" in explain


def _institution_explain(institution: dict) -> str:
    return build_analysis_sections({"institution": institution})["explain"]


def test_unavailable_institution_remains_unintegrated():
    explain = _institution_explain({"available": False})

    assert "籌碼面：尚未整合" in explain


def test_all_institutions_buy_and_summary_is_preserved():
    explain = _institution_explain(
        {
            "available": True,
            "foreign_buy_sell": 12345,
            "investment_buy_sell": 2100,
            "dealer_buy_sell": 500,
            "three_major_buy_sell": 14945,
            "summary": "籌碼偏多",
        }
    )

    assert "外資：\n買超 12,345 張" in explain
    assert "投信：\n買超 2,100 張" in explain
    assert "自營商：\n買超 500 張" in explain
    assert "三大法人：\n合計買超 14,945 張" in explain
    assert "AI判定：\n籌碼偏多" in explain


def test_all_institutions_sell():
    explain = _institution_explain(
        {
            "available": True,
            "foreign_buy_sell": -8200,
            "investment_buy_sell": -1000,
            "dealer_buy_sell": -300,
            "three_major_buy_sell": -9500,
            "summary": "籌碼偏空",
        }
    )

    assert "外資：\n賣超 8,200 張" in explain
    assert "投信：\n賣超 1,000 張" in explain
    assert "自營商：\n賣超 300 張" in explain
    assert "三大法人：\n合計賣超 9,500 張" in explain
    assert "AI判定：\n籌碼偏空" in explain


def test_missing_institution_values_are_omitted():
    explain = _institution_explain(
        {
            "available": True,
            "foreign_buy_sell": 100,
            "investment_buy_sell": None,
            "dealer_buy_sell": None,
            "three_major_buy_sell": 100,
            "summary": "籌碼中性偏多",
        }
    )

    assert "外資：\n買超 100 張" in explain
    assert "投信：" not in explain
    assert "自營商：" not in explain
    assert "三大法人：\n合計買超 100 張" in explain


def test_flat_institution_is_displayed():
    explain = _institution_explain(
        {
            "available": True,
            "foreign_buy_sell": 0,
            "summary": "籌碼中性",
        }
    )

    assert "外資：\n持平" in explain
    assert "AI判定：\n籌碼中性" in explain


def test_technical_layout_uses_label_value_blocks():
    explain = build_analysis_sections(
        {
            "core": {
                "ma_signal": "站上 MA20",
                "macd_signal": "死亡交叉",
                "kd_signal": "死亡交叉",
                "rsi_signal": "50.4（健康區間）",
            }
        }
    )["explain"]

    assert "技術面：\n\n均線：\n站上 MA20" in explain
    assert "動能：\nMACD、KD 死亡交叉" in explain
    assert "RSI：\n50.4（健康區間）" in explain


def test_market_sentiment_layout():
    explain = build_analysis_sections(
        {"core": {"consensus_score": 60, "trend": "多頭"}}
    )["explain"]

    assert "市場情緒：\n\n技術指標共識度：\n\n60%" in explain
    assert "目前偏向：\n\n偏多" in explain
    assert "新聞：\n\n尚未整合" in explain
