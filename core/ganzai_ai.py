from services.score_service import calculate_ai_index
from services.strategy_service import get_strategy
from services.risk_service import calculate_risk
from services.decision_service import get_decision

from core.health_engine import calculate_health
from core.consensus_engine import calculate_consensus
from core.explain_engine import explain_ai_index
from core.shopkeeper_engine import get_shopkeeper_advice


class GanzaiAI:

    def __init__(self, stock):
        self.stock = stock

        self.ai_index = None
        self.health = None
        self.consensus = None
        self.strategy = None
        self.risk = None
        self.decision = None
        self.explain = None
        self.shopkeeper = None

    def run(self):

        self.ai_index = calculate_ai_index(self.stock)
        self.stock["ai_index"] = self.ai_index

        self.health = calculate_health(self.stock)
        self.consensus = calculate_consensus(self.stock)
        self.strategy = get_strategy(self.stock)
        self.risk = calculate_risk(self.stock)
        self.decision = get_decision(self.stock)

        self.explain = explain_ai_index(
            self.stock,
            {"ai_index": self.ai_index}
        )

        self.shopkeeper = get_shopkeeper_advice(
            self.ai_index["score"],
            self.risk["risk_score"]
        )

        return {
            "ai_index": self.ai_index,
            "health": self.health,
            "consensus": self.consensus,
            "strategy": self.strategy,
            "risk": self.risk,
            "decision": self.decision,
            "explain": self.explain,
            "shopkeeper": self.shopkeeper,
        }