from core.engines.score_engine import ScoreEngine
from core.engines.decision_engine import DecisionEngine
from core.engines.consensus_engine import ConsensusEngine
from core.consensus_engine import calculate_consensus
from core.data_quality import calculate_confidence, calculate_data_completeness


class GanzaiAIv2:
    """
    GanzaiAI v2 Facade

    AI Core v2 的統一入口。
    目前整合：
    - ScoreEngine
    - DecisionEngine
    - ConsensusEngine
    """

    def __init__(self, stock: dict):
        self.stock = stock or {}
        self.score_engine = ScoreEngine()
        self.decision_engine = DecisionEngine()
        self.consensus_engine = ConsensusEngine()

    def run(self) -> dict:
        consensus_result = self.consensus_engine.run(self.stock)
        stock_with_consensus = {
            **self.stock,
            **consensus_result,
        }

        score_result = self.score_engine.run(stock_with_consensus)
        data_completeness = calculate_data_completeness(stock_with_consensus)
        consensus_score = calculate_consensus(stock_with_consensus).get("consensus_score")
        confidence = calculate_confidence(
            stock_with_consensus,
            consensus_score,
            consensus_result,
        )
        decision_result = self.decision_engine.run(score_result, confidence)

        return {
            "score": score_result.get("score"),
            "data_completeness": data_completeness,
            "star": score_result.get("star"),
            "star_text": score_result.get("star_text"),
            "grade": score_result.get("grade"),
            "score_label": score_result.get("label"),
            "score_color": score_result.get("color"),

            "decision": decision_result.get("decision"),
            "confidence": confidence,
            "decision_action": decision_result.get("action"),
            "decision_color": decision_result.get("color"),
            "decision_emoji": decision_result.get("emoji"),

            "risk_level": "未評估",

            "trend": consensus_result.get("trend"),
            "ma_signal": consensus_result.get("ma_signal"),
            "macd_signal": consensus_result.get("macd_signal"),
            "rsi_signal": consensus_result.get("rsi_signal"),
            "kd_signal": consensus_result.get("kd_signal"),

            "strategy": "觀望",

            "shopkeeper_message": self._shopkeeper_message(
                score_result,
                decision_result,
                consensus_result,
            ),

            "ai_summary": self._summary(
                score_result,
                decision_result,
                consensus_result,
            ),

            "explain": self._explain(
                score_result,
                decision_result,
                consensus_result,
            ),

            "_raw": {
                "score": score_result,
                "decision": decision_result,
                "consensus": consensus_result,
            },
        }

    def _summary(
        self,
        score_result: dict,
        decision_result: dict,
        consensus_result: dict,
    ) -> str:
        return (
            f"AI 評分 {score_result.get('score')} 分，"
            f"目前判斷為「{decision_result.get('decision')}」。"
            f"趨勢為 {consensus_result.get('trend')}，"
            f"技術面顯示 {consensus_result.get('ma_signal')}。"
        )

    def _explain(
        self,
        score_result: dict,
        decision_result: dict,
        consensus_result: dict,
    ) -> list:
        return [
            f"AI 分數為 {score_result.get('score')} 分，等級 {score_result.get('grade')}。",
            f"決策為 {decision_result.get('decision')}，信心值 {decision_result.get('confidence')}%。",
            f"趨勢判斷：{consensus_result.get('trend')}。",
            f"均線訊號：{consensus_result.get('ma_signal')}。",
            f"MACD 訊號：{consensus_result.get('macd_signal')}。",
            f"RSI 訊號：{consensus_result.get('rsi_signal')}。",
        ]

    def _shopkeeper_message(
        self,
        score_result: dict,
        decision_result: dict,
        consensus_result: dict,
    ) -> str:
        score = score_result.get("score", 0)
        decision = decision_result.get("decision", "觀察")
        trend = consensus_result.get("trend", "未判定")

        if score >= 80:
            return f"阿柑店長看法：目前{trend}，判斷偏強，但不要追太急，建議分批看。"

        if score >= 60:
            return f"阿柑店長看法：目前是{decision}，可以先觀察，等訊號更明確。"

        return "阿柑店長看法：目前風險偏高，先保守一點，不急著進場。"
