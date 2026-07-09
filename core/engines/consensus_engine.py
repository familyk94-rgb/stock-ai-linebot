class ConsensusEngine:
    """
    Consensus Engine v1.0

    將技術指標轉成好懂的訊號：
    - trend
    - ma_signal
    - macd_signal
    - rsi_signal
    - kd_signal
    """

    def run(self, stock: dict) -> dict:
        technical = stock.get("technical") or {}

        return {
            "trend": self._trend(stock, technical),
            "ma_signal": self._ma_signal(stock, technical),
            "macd_signal": self._macd_signal(technical),
            "rsi_signal": self._rsi_signal(technical),
            "kd_signal": self._kd_signal(technical),
        }

    def _trend(self, stock: dict, technical: dict) -> str:
        price = stock.get("price")
        ma20 = technical.get("ma20")
        ma60 = technical.get("ma60")

        try:
            price = float(price)
            ma20 = float(ma20)
            ma60 = float(ma60)

            if price >= ma20 >= ma60:
                return "多頭"
            if price < ma20 < ma60:
                return "空頭"
            return "整理"
        except Exception:
            return "未判定"

    def _ma_signal(self, stock: dict, technical: dict) -> str:
        price = stock.get("price")
        ma5 = technical.get("ma5")
        ma20 = technical.get("ma20")
        ma60 = technical.get("ma60")

        try:
            price = float(price)
            ma5 = float(ma5)
            ma20 = float(ma20)
            ma60 = float(ma60)

            if price >= ma5 >= ma20 >= ma60:
                return "多頭排列"
            if price < ma5 < ma20 < ma60:
                return "空頭排列"
            if price >= ma20:
                return "站上MA20"
            if price < ma20:
                return "跌破MA20"
            return "均線整理"
        except Exception:
            return "未判定"

    def _macd_signal(self, technical: dict) -> str:
        macd = technical.get("macd")
        signal = technical.get("signal")
        histogram = technical.get("histogram")

        try:
            macd = float(macd)
            signal = float(signal)

            if histogram is not None:
                histogram = float(histogram)

                if macd > signal and histogram > 0:
                    return "黃金交叉"
                if macd < signal and histogram < 0:
                    return "死亡交叉"

            if macd > signal:
                return "偏多"
            if macd < signal:
                return "偏空"

            return "中性"
        except Exception:
            return "未判定"

    def _rsi_signal(self, technical: dict) -> str:
        rsi = technical.get("rsi")

        try:
            rsi = float(rsi)

            if 45 <= rsi <= 65:
                return f"{rsi:.1f} 健康區間"
            if 65 < rsi <= 75:
                return f"{rsi:.1f} 偏熱"
            if rsi > 75:
                return f"{rsi:.1f} 過熱"
            if 35 <= rsi < 45:
                return f"{rsi:.1f} 偏弱"
            if rsi < 35:
                return f"{rsi:.1f} 超賣"

            return f"{rsi:.1f} 中性"
        except Exception:
            return "未判定"

    def _kd_signal(self, technical: dict) -> str:
        k = technical.get("k")
        d = technical.get("d")

        try:
            k = float(k)
            d = float(d)

            if k > d and k < 80:
                return "黃金交叉"
            if k > d and k >= 80:
                return "高檔偏熱"
            if k < d and k > 20:
                return "死亡交叉"
            if k < d and k <= 20:
                return "低檔偏弱"

            return "中性"
        except Exception:
            return "未判定"