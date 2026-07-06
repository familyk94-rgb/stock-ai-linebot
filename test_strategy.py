from services.market_service import get_market_info
from services.strategy_service import get_strategy

stock = get_market_info("2330")
strategy = get_strategy(stock)

print(strategy)