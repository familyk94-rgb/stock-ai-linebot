from services.market_service import get_market_info

stock = get_market_info("3481")

print(stock["stock_id"])
print(stock["stock_name"])