"""Four-aspect analysis grid for Dashboard V3."""

from app.flex.dashboard_card import _safe_number
from app.flex.design_system import BRAND, MUTED, SUBTLE, TEXT, card


def build_analysis_grid(
    *,
    technical_score=None,
    technical_summary=None,
    financial_score=None,
    financial_summary=None,
    institution_score=None,
    institution_summary=None,
    news_score=None,
    news_summary=None,
) -> dict:
    cells = [
        _cell("📈 技術", technical_score, technical_summary),
        _cell("💰 基本", financial_score, financial_summary),
        _cell("🏦 籌碼", institution_score, institution_summary),
        _cell("📰 新聞", news_score, news_summary),
    ]
    return card([
        {"type": "text", "text": "多面向分析", "size": "md", "weight": "bold", "color": TEXT},
        {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": cells[:2]},
        {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": cells[2:]},
    ])


def _cell(title, score, summary) -> dict:
    number = _safe_number(score)
    score_text = "—" if number is None else str(round(max(0, min(100, number))))
    summary_text = summary.strip() if isinstance(summary, str) and summary.strip() else "資料未提供"
    return {
        "type": "box", "layout": "vertical", "flex": 1, "paddingAll": "12px",
        "backgroundColor": SUBTLE, "cornerRadius": "10px", "spacing": "xs",
        "contents": [
            {"type": "text", "text": title, "size": "sm", "weight": "bold", "color": TEXT},
            {"type": "text", "text": score_text, "size": "xl", "weight": "bold", "color": BRAND},
            {"type": "text", "text": summary_text, "size": "xs", "color": MUTED, "wrap": True, "maxLines": 2},
        ],
    }
