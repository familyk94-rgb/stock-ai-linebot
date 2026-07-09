from pprint import pprint
from services.market_service import get_market_info

stock = get_market_info("2330")

print(stock.keys())
print("core 是否存在：", "core" in stock)
pprint(stock["core"])