"""LINE push adapter for channel-neutral notification events."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from linebot.v3.messaging import PushMessageRequest, TextMessage

from core.models.notification_event import NotificationEvent


MAX_LINE_ALERT_MESSAGE_LENGTH = 2_000
_TAIPEI = ZoneInfo("Asia/Taipei")


class LinePushError(RuntimeError):
    """Safe adapter error raised when a LINE push cannot be completed."""


class LinePushSender:
    """Deliver one notification event as one LINE text push request."""

    channel = "line"

    def __init__(self, messaging_api) -> None:
        if messaging_api is None or not callable(
            getattr(messaging_api, "push_message", None)
        ):
            raise TypeError("messaging_api must provide callable push_message")
        self._messaging_api = messaging_api

    def send(self, event: NotificationEvent) -> None:
        if not isinstance(event, NotificationEvent):
            raise TypeError("event must be NotificationEvent")

        message = format_line_alert_message(event)
        request = PushMessageRequest(
            to=event.recipient_id,
            messages=[TextMessage(text=message)],
        )
        try:
            self._messaging_api.push_message(request)
        except Exception as error:
            raise LinePushError(
                f"LINE push message failed: {type(error).__name__}"
            ) from error
        return None


def format_line_alert_message(event: NotificationEvent) -> str:
    """Build the deterministic Traditional Chinese LINE alert text."""

    if not isinstance(event, NotificationEvent):
        raise TypeError("event must be NotificationEvent")

    direction = "高於" if event.condition == "GT" else "低於"
    triggered_at = datetime.fromisoformat(event.triggered_at).astimezone(_TAIPEI)
    message = (
        "股市柑仔店｜價格提醒\n\n"
        f"股票：{event.stock_id}\n"
        f"條件：{direction} {_format_decimal(event.target_price)} 元\n"
        f"目前價格：{_format_decimal(event.current_price)} 元\n"
        f"觸發時間：{triggered_at:%Y-%m-%d %H:%M}\n\n"
        f"價格已{direction}設定提醒價。"
    )
    if not message or len(message) > MAX_LINE_ALERT_MESSAGE_LENGTH:
        raise LinePushError("LINE push message length is invalid")
    return message


def _format_decimal(value: Decimal) -> str:
    text = format(value, ",f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
