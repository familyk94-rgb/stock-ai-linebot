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

    assert "EPS：5.26" in explain
    assert "本益比(PER)：" not in explain
    assert "AI判定：基本面中性" in explain


def test_fundamental_with_only_per():
    explain = _explain(
        {
            "available": True,
            "pe": 18.26,
            "summary": "基本面中性",
        }
    )

    assert "本益比(PER)：18.3" in explain
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
        "基本面：\n"
        "EPS：5.26\n"
        "本益比(PER)：18.3\n"
        "股價淨值比(PBR)：2.5\n"
        "殖利率：3.2%\n"
        "月營收YoY：12.6%\n"
        "AI判定：基本面偏佳"
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
    assert "本益比(PER)：20.0" in explain
    assert "股價淨值比(PBR)：" not in explain
    assert "殖利率：2.0%" in explain
    assert "月營收YoY：" not in explain
    assert "AI判定：基本面偏弱" in explain
