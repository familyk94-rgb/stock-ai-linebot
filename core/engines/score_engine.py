class ScoreEngine:
    """
    Score Engine v1.0

    負責輸出：
    - AI 分數 score
    - 星等 star
    - 等級 grade
    - 標籤 label
    - 顏色 color
    - 分數明細 breakdown
    """

    def run(self, stock: dict) -> dict:
        technical = stock.get("technical") or {}

        breakdown = {
            "trend": self._score_trend(stock, technical),   # 25
            "ma": self._score_ma(stock, technical),         # 15
            "macd": self._score_macd(technical),            # 15
            "rsi": self._score_rsi(technical),              # 10
            "kd": self._score_kd(technical),                # 10
            "volume": self._score_volume(stock),            # 10
            "risk": self._score_risk(stock),                # 15
        }

        score = sum(breakdown.values())
        score = max(0, min(100, int(score)))

        return {
            "score": score,
            "star": self._star(score),
            "star_text": self._star_text(score),
            "grade": self._grade(score),
            "label": self._label(score),
            "color": self._color(score),
            "breakdown": breakdown,
        }

    def _score_trend(self, stock: dict, technical: dict) -> int:
        trend = str(stock.get("trend") or technical.get("trend") or "")

        if "多" in trend:
            return 25
        if "空" in trend:
            return 5
        return 15

    def _score_ma(self, stock: dict, technical: dict) -> int:
        close = stock.get("price") or technical.get("close")
        ma5 = technical.get("ma5")
        ma20 = technical.get("ma20")
        ma60 = technical.get("ma60")

        try:
            close = float(close)
            ma5 = float(ma5)
            ma20 = float(ma20)

            if ma60 is not None:
                ma60 = float(ma60)
                if close >= ma5 >= ma20 >= ma60:
                    return 15

            if close >= ma5 >= ma20:
                return 13
            if close >= ma20:
                return 10
            if close < ma20:
                return 5

        except Exception:
            pass

        return 8

    def _score_macd(self, technical: dict) -> int:
        macd = technical.get("macd")
        signal = technical.get("signal")
        histogram = technical.get("histogram")

        try:
            macd = float(macd)
            signal = float(signal)

            if histogram is not None:
                histogram = float(histogram)
                if macd > signal and histogram > 0:
                    return 15

            if macd > signal:
                return 12

            return 5

        except Exception:
            pass

        return 8

    def _score_rsi(self, technical: dict) -> int:
        rsi = technical.get("rsi")

        try:
            rsi = float(rsi)

            if 45 <= rsi <= 65:
                return 10
            if 35 <= rsi < 45:
                return 7
            if 65 < rsi <= 75:
                return 7
            if 30 <= rsi < 35:
                return 5
            if 75 < rsi <= 80:
                return 5
            if rsi < 30:
                return 4
            if rsi > 80:
                return 3

        except Exception:
            pass

        return 5

    def _score_kd(self, technical: dict) -> int:
        k = technical.get("k")
        d = technical.get("d")

        try:
            k = float(k)
            d = float(d)

            if k > d and k < 80:
                return 10
            if k > d:
                return 7
            if k < d:
                return 5

        except Exception:
            pass

        return 5

    def _score_volume(self, stock: dict) -> int:
        volume = stock.get("volume")

        try:
            volume = float(volume)

            if volume > 0:
                return 8

        except Exception:
            pass

        return 5

    def _score_risk(self, stock: dict) -> int:
        return 10

    def _star(self, score: int) -> int:
        if score >= 90:
            return 5
        if score >= 80:
            return 4
        if score >= 70:
            return 3
        if score >= 60:
            return 2
        return 1

    def _star_text(self, score: int) -> str:
        star = self._star(score)
        return "★" * star + "☆" * (5 - star)

    def _grade(self, score: int) -> str:
        if score >= 90:
            return "S"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    def _label(self, score: int) -> str:
        if score >= 90:
            return "極佳"
        if score >= 80:
            return "良好"
        if score >= 70:
            return "普通"
        if score >= 60:
            return "偏弱"
        return "風險高"

    def _color(self, score: int) -> str:
        if score >= 90:
            return "#16A34A"
        if score >= 80:
            return "#22C55E"
        if score >= 70:
            return "#F59E0B"
        if score >= 60:
            return "#EF4444"
        return "#991B1B"