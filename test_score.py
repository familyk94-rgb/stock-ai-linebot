from services.market_service import get_market_info
from services.score_service import calculate_ai_index

def main():
    stock = get_market_info("2330")
    score = calculate_ai_index(stock)
    print(score)


if __name__ == "__main__":
    main()
