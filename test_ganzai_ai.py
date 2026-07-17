from pprint import pprint

from services.market_service import get_market_info
from core.ganzai_ai import GanzaiAI

def main():
    stock = get_market_info("2330")
    ai = GanzaiAI(stock)
    analysis = ai.run()
    pprint(analysis)


if __name__ == "__main__":
    main()
