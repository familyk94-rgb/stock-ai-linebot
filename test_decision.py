from services.market_service import get_market_info
from services.decision_service import get_decision

stock = get_market_info("2330")
decision = get_decision(stock)

print(decision)