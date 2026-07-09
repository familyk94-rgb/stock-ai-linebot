from core.market.market_engine import MarketEngine


def test_market_engine_output():
    result = MarketEngine().run("3481")

    assert isinstance(result, dict)
    assert "stock_code" in result
    assert "stock_name" in result
    assert "date" in result
    assert "price" in result
    assert "volume" in result
    assert "technical" in result
    assert "financial" in result
    assert "institution" in result
    assert "news" in result