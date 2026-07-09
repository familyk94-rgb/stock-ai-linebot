from core.engines.score_engine import ScoreEngine


class GanzaiAIv2:
    """
    GanzaiAI v2 Facade

    AI Core 的統一入口。
    目前 Sprint 2-4 先串接 ScoreEngine。
    後續再加入 RiskEngine、DecisionEngine、ConsensusEngine。
    """

    def __init__(self, stock: dict):
        self.stock = stock or {}
        self.score_engine = ScoreEngine()

    def run(self) -> dict:
        score_result = self.score_engine.run(self.stock)

        return {
            "score": score_result.get("score"),
            "star": score_result.get("star"),
            "star_text": score_result.get("star_text"),
            "grade": score_result.get("grade"),
            "score_label": score_result.get("label"),
            "score_color": score_result.get("color"),

            "decision": "觀察",
            "risk_level": "未評估",

            "trend": self.stock.get("trend", "未判定"),
            "ma_signal": self.stock.get("ma_signal", "未判定"),
            "macd_signal": self.stock.get("macd_signal", "未判定"),
            "rsi_signal": self.stock.get("rsi_signal", "未判定"),

            "strategy": "觀望",

            "shopkeeper_message": "阿柑店長看法：目前先觀察，等更多訊號確認。",
            "ai_summary": "AI Core v2 已啟用，目前已完成 AI 評分模組。",
            "explain": [
                f"AI 分數為 {score_result.get('score')} 分。",
                f"等級為 {score_result.get('grade')}，狀態為 {score_result.get('label')}。",
                "目前 Sprint 2-4 先完成 Score Engine 串接。",
            ],

            "_raw": {
                "score": score_result,
            },
        }