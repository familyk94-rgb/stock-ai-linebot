from services.technical_service import get_technical_indicators


class TechnicalEngine:
    """
    Technical Engine v1.0
    只負責取得技術指標，不呼叫 AI Core。
    """

    def run(self, stock_code: str) -> dict:
        stock_code = str(stock_code).strip()

        technical = get_technical_indicators(stock_code) or {}

        return technical