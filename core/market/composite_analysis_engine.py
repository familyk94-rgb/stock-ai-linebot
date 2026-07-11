"""Deterministic aggregation of existing market analysis modules."""

from __future__ import annotations

import math
from typing import Any


MODULES = (
    ("technical", "技術面", 35),
    ("financial", "基本面", 25),
    ("institution", "籌碼面", 20),
    ("news", "新聞面", 20),
)
TOTAL_MODULES = len(MODULES)


class CompositeAnalysisEngine:
    """Combine module scores without mutating inputs or fetching data."""

    def analyze(
        self,
        technical: Any,
        financial: Any,
        institution: Any,
        news: Any,
    ) -> dict:
        try:
            return _analyze_modules(
                {
                    "technical": technical,
                    "financial": financial,
                    "institution": institution,
                    "news": news,
                }
            )
        except Exception:
            return composite_fallback()


def _analyze_modules(modules: dict[str, Any]) -> dict:
    valid_scores = {
        key: score
        for key, _, _ in MODULES
        if (score := _valid_score(modules.get(key))) is not None
    }
    if not valid_scores:
        return composite_fallback()

    available_weight = sum(
        base_weight
        for key, _, base_weight in MODULES
        if key in valid_scores
    )
    contributions = {}
    for key, _, base_weight in MODULES:
        score = valid_scores.get(key)
        if score is None:
            contributions[key] = _unavailable_contribution(base_weight)
            continue

        normalized_weight = round(base_weight / available_weight * 100, 2)
        contribution = round(score * normalized_weight / 100, 2)
        contributions[key] = {
            "available": True,
            "score": score,
            "base_weight": base_weight,
            "normalized_weight": normalized_weight,
            "contribution": contribution,
        }

    exact_score = sum(
        valid_scores[key] * base_weight / available_weight
        for key, _, base_weight in MODULES
        if key in valid_scores
    )
    score = max(0, min(100, round(exact_score)))
    available_modules = len(valid_scores)
    coverage = available_modules * 25

    return {
        "available": True,
        "score": score,
        "summary": _summary(score),
        "coverage": coverage,
        "available_modules": available_modules,
        "total_modules": TOTAL_MODULES,
        "contributions": contributions,
        "signals": _signals(contributions, coverage),
    }


def _valid_score(module: Any) -> int | float | None:
    if not isinstance(module, dict) or module.get("available") is not True:
        return None
    score = module.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if not math.isfinite(score):
        return None
    return max(0, min(100, score))


def _summary(score: int) -> str:
    if score >= 80:
        return "整體市場訊號偏多"
    if score >= 60:
        return "整體市場訊號中性偏多"
    if score >= 40:
        return "整體市場訊號中性"
    if score >= 20:
        return "整體市場訊號中性偏空"
    return "整體市場訊號偏空"


def _signals(contributions: dict, coverage: int) -> list[str]:
    signals = []
    for key, label, _ in MODULES:
        module = contributions[key]
        if module["available"]:
            signals.append(f"{label}：{round(module['score'])} 分")
        else:
            signals.append(f"{label}：資料不足")
    signals.append(f"綜合分析資料覆蓋率：{coverage}%")
    return signals


def _unavailable_contribution(base_weight: int) -> dict:
    return {
        "available": False,
        "score": None,
        "base_weight": base_weight,
        "normalized_weight": 0,
        "contribution": 0,
    }


def composite_fallback() -> dict:
    contributions = {
        key: _unavailable_contribution(base_weight)
        for key, _, base_weight in MODULES
    }
    return {
        "available": False,
        "score": 50,
        "summary": "綜合分析資料不足",
        "coverage": 0,
        "available_modules": 0,
        "total_modules": TOTAL_MODULES,
        "contributions": contributions,
        "signals": _signals(contributions, 0),
    }
