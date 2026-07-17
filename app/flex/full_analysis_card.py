"""Existing AI summary and explain content in one product card."""

from app.flex.design_system import MUTED, TEXT, card


def build_full_analysis_card(*, summary=None, explain=None) -> dict:
    summary_text = summary if isinstance(summary, str) and summary.strip() else "目前資料不足，建議等待更多訊號。"
    explain_text = explain if isinstance(explain, str) and explain.strip() else "尚未產生完整解釋。"
    return card([
        {"type": "text", "text": "📈 完整分析", "size": "md", "weight": "bold", "color": TEXT},
        {"type": "text", "text": summary_text, "size": "sm", "color": TEXT, "wrap": True},
        {"type": "separator", "margin": "md"},
        {"type": "text", "text": "分析原因", "size": "xs", "color": MUTED, "margin": "md"},
        {"type": "text", "text": explain_text, "size": "sm", "color": TEXT, "wrap": True},
    ])
