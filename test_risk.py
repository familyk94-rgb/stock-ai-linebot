from services.market_service import get_market_info
from services.risk_service import calculate_risk

def main():
    stock = get_market_info("2330")
    risk = calculate_risk(stock)
    print(risk)


if __name__ == "__main__":
    main()
