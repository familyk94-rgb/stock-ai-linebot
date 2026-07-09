class DecisionEngine:
    """
    Decision Engine v1.0

    根據 AI Score 產生：
    - decision 決策
    - confidence 信心值
    - action 操作方向
    - color 顏色
    """

    def run(self, score_result: dict) -> dict:
        score = int(score_result.get("score", 0))

        decision = self._decision(score)

        return {
            "decision": decision["decision"],
            "confidence": self._confidence(score),
            "action": decision["action"],
            "color": decision["color"],
            "emoji": decision["emoji"],
        }

    def _decision(self, score: int) -> dict:
        if score >= 90:
            return {
                "decision": "強烈買進",
                "action": "可積極關注，但仍需分批布局",
                "color": "#16A34A",
                "emoji": "🟢",
            }

        if score >= 80:
            return {
                "decision": "買進",
                "action": "可考慮分批布局",
                "color": "#22C55E",
                "emoji": "🟢",
            }

        if score >= 70:
            return {
                "decision": "偏多",
                "action": "趨勢偏多，可等待拉回",
                "color": "#84CC16",
                "emoji": "🟢",
            }

        if score >= 60:
            return {
                "decision": "觀察",
                "action": "訊號尚未明確，先觀察",
                "color": "#F59E0B",
                "emoji": "🟡",
            }

        if score >= 50:
            return {
                "decision": "偏空",
                "action": "短線偏弱，不宜追價",
                "color": "#F97316",
                "emoji": "🟠",
            }

        if score >= 40:
            return {
                "decision": "減碼",
                "action": "風險升高，建議降低部位",
                "color": "#EF4444",
                "emoji": "🔴",
            }

        return {
            "decision": "賣出",
            "action": "趨勢明顯轉弱，應嚴格控管風險",
            "color": "#991B1B",
            "emoji": "⛔",
        }

    def _confidence(self, score: int) -> int:
        if score >= 90:
            return 95
        if score >= 80:
            return 90
        if score >= 70:
            return 85
        if score >= 60:
            return 75
        if score >= 50:
            return 70
        if score >= 40:
            return 80
        return 90