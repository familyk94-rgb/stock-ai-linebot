import math


def build_composite_card(
    available=False,
    score=None,
    summary=None,
    coverage=None,
) -> dict:
    valid = (
        available is True
        and _is_finite_number(score)
        and isinstance(summary, str)
        and bool(summary.strip())
        and _is_finite_number(coverage)
    )

    contents = [
        {
            "type": "text",
            "text": "綜合分析",
            "weight": "bold",
            "size": "md",
            "color": "#111827",
        }
    ]

    if not valid:
        contents.append(
            {
                "type": "text",
                "text": "資料不足",
                "size": "sm",
                "color": "#6B7280",
                "wrap": True,
            }
        )
    else:
        contents.extend(
            [
                _row("綜合評分", f"{round(_clamp(score))} 分"),
                _row("摘要", summary.strip(), wrap=True),
                _row("分析面向覆蓋率", f"{round(_clamp(coverage))}%"),
            ]
        )

    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "spacing": "sm",
        "contents": contents,
    }


def _is_finite_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _clamp(value: int | float) -> int | float:
    return max(0, min(100, value))


def _row(label: str, value: str, wrap: bool = False) -> dict:
    value_text = {
        "type": "text",
        "text": value,
        "size": "sm",
        "align": "end",
        "weight": "bold",
        "flex": 2,
    }
    if wrap:
        value_text["wrap"] = True

    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {
                "type": "text",
                "text": label,
                "size": "sm",
                "color": "#6B7280",
                "flex": 1,
            },
            value_text,
        ],
    }
