from core.consensus_engine import calculate_consensus
from core.engines.consensus_engine import ConsensusEngine
from core.engines.decision_engine import DecisionEngine
from core.engines.score_engine import ScoreEngine
from core.health_engine import calculate_health
from services.risk_service import calculate_risk


class GanzaiAIv2:
    """整合市場資料與既有分析引擎，提供統一的 AI Core 輸出。"""

    def __init__(self, stock: dict):
        self.stock = stock or {}
        self.score_engine = ScoreEngine()
        self.decision_engine = DecisionEngine()
        self.consensus_engine = ConsensusEngine()

    def run(self) -> dict:
        technical_signals = self.consensus_engine.run(self.stock)
        stock_with_signals = {
            **self.stock,
            **technical_signals,
        }

        score_result = self.score_engine.run(stock_with_signals)
        decision_result = self.decision_engine.run(score_result)
        health_result = calculate_health(stock_with_signals)
        consensus_result = calculate_consensus(stock_with_signals)
        risk_result = calculate_risk(stock_with_signals)

        return {
            "score": score_result.get("score"),
            "health_score": health_result.get("health_score"),
            "consensus_score": consensus_result.get("consensus_score"),
            "decision": decision_result.get("decision"),
            "risk_score": risk_result.get("risk_score"),
            "risk_level": risk_result.get("risk_level"),
            "confidence": decision_result.get("confidence"),
            "technical_signals": technical_signals,

            "star": score_result.get("star"),
            "star_text": score_result.get("star_text"),
            "grade": score_result.get("grade"),
            "score_label": score_result.get("label"),
            "score_color": score_result.get("color"),
            "health_level": health_result.get("health_level"),
            "consensus_level": consensus_result.get("consensus_level"),

            "trend": technical_signals.get("trend"),
            "ma_signal": technical_signals.get("ma_signal"),
            "macd_signal": technical_signals.get("macd_signal"),
            "rsi_signal": technical_signals.get("rsi_signal"),
            "kd_signal": technical_signals.get("kd_signal"),

            "decision_action": decision_result.get("action"),
            "decision_color": decision_result.get("color"),
            "decision_emoji": decision_result.get("emoji"),
            "stop_loss_price": risk_result.get("stop_loss_price"),
            "take_profit_price": risk_result.get("take_profit_price"),

            "strategy": "觀望",
            "shopkeeper_message": self._shopkeeper_message(
                score_result,
                decision_result,
                technical_signals,
            ),
            "ai_summary": self._summary(
                score_result,
                decision_result,
                technical_signals,
            ),
            "explain": self._explain(
                score_result,
                decision_result,
                technical_signals,
                health_result,
                consensus_result,
                risk_result,
            ),
            "_raw": {
                "score": score_result,
                "health": health_result,
                "consensus": consensus_result,
                "decision": decision_result,
                "risk": risk_result,
                "technical_signals": technical_signals,
            },
        }

    def _summary(self, score_result, decision_result, technical_signals) -> str:
        return (
            f"AI 評分 {score_result.get('score')} 分，"
            f"目前判斷為「{decision_result.get('decision')}」。"
            f"趨勢為 {technical_signals.get('trend')}，"
            f"技術面顯示 {technical_signals.get('ma_signal')}。"
        )

    def _explain(
        self,
        score_result,
        decision_result,
        technical_signals,
        health_result,
        consensus_result,
        risk_result,
    ) -> list:
        return [
            f"AI 分數為 {score_result.get('score')} 分，等級 {score_result.get('grade')}。",
            f"健康度 {health_result.get('health_score')} 分，共識度 {consensus_result.get('consensus_score')} 分。",
            f"決策為 {decision_result.get('decision')}，信心值 {decision_result.get('confidence')}%。",
            f"風險分數 {risk_result.get('risk_score')}，風險等級 {risk_result.get('risk_level')}。",
            f"趨勢判斷：{technical_signals.get('trend')}。",
            f"均線訊號：{technical_signals.get('ma_signal')}。",
            f"MACD 訊號：{technical_signals.get('macd_signal')}。",
            f"RSI 訊號：{technical_signals.get('rsi_signal')}。",
        ]

    def _shopkeeper_message(
        self,
        score_result,
        decision_result,
        technical_signals,
    ) -> str:
        score = score_result.get("score", 0)
        decision = decision_result.get("decision", "觀察")
        trend = technical_signals.get("trend", "未判定")

        if score >= 80:
            return f"阿柑店長看法：目前{trend}，判斷偏強，但不要追太急，建議分批看。"
        if score >= 60:
            return f"阿柑店長看法：目前是{decision}，可以先觀察，等訊號更明確。"
        return "阿柑店長看法：目前風險偏高，先保守一點，不急著進場。"


GanzaiAI = GanzaiAIv2
