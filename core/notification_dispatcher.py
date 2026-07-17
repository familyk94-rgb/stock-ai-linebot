"""Channel-neutral notification dispatcher."""

from __future__ import annotations

import re
from collections.abc import Iterable

from core.models.dispatch_result import (
    MAX_DISPATCH_ERROR_MESSAGE_LENGTH,
    DispatchItemResult,
    DispatchReport,
)
from core.models.notification_event import NotificationEvent
from core.ports.notification_sender import NotificationSender


_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(access[_-]?token|reply[_-]?token|line[_-]?token|api[_-]?key|"
    r"request[_-]?headers?|credentials?|certificate|token|secret|password|"
    r"authorization|cookie)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")


class NotificationDispatcherError(Exception):
    """Base error for dispatcher configuration problems."""


class InvalidNotificationChannelError(NotificationDispatcherError):
    """Raised when a sender or dispatch channel is blank or invalid."""


class DuplicateNotificationChannelError(NotificationDispatcherError):
    """Raised when two senders register the same normalized channel."""


class UnknownNotificationChannelError(NotificationDispatcherError):
    """Raised when dispatch targets a channel without a registered sender."""


class NotificationDispatcher:
    def __init__(self, senders: Iterable[NotificationSender]) -> None:
        registry = {}
        for sender in senders:
            channel = _channel(sender.channel)
            if channel in registry:
                raise DuplicateNotificationChannelError(
                    f"duplicate notification channel: {channel}"
                )
            registry[channel] = sender
        self._senders = registry

    def dispatch(
        self,
        events: Iterable[NotificationEvent],
        *,
        channel: str,
    ) -> DispatchReport:
        selected_channel = _channel(channel)
        try:
            sender = self._senders[selected_channel]
        except KeyError:
            raise UnknownNotificationChannelError(
                f"unknown notification channel: {selected_channel}"
            ) from None

        normalized_events = tuple(events)
        for event in normalized_events:
            if not isinstance(event, NotificationEvent):
                raise TypeError("events must contain NotificationEvent")

        results = []
        succeeded = 0
        for event in normalized_events:
            try:
                sender.send(event)
            except Exception as error:
                results.append(
                    DispatchItemResult(
                        alert_id=event.alert_id,
                        recipient_id=event.recipient_id,
                        channel=selected_channel,
                        success=False,
                        error_type=type(error).__name__,
                        error_message=_safe_error_message(error),
                    )
                )
            else:
                succeeded += 1
                results.append(
                    DispatchItemResult(
                        alert_id=event.alert_id,
                        recipient_id=event.recipient_id,
                        channel=selected_channel,
                        success=True,
                    )
                )

        attempted = len(results)
        return DispatchReport(
            channel=selected_channel,
            attempted=attempted,
            succeeded=succeeded,
            failed=attempted - succeeded,
            results=tuple(results),
        )


def _channel(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidNotificationChannelError("notification channel must be nonblank")
    return value.strip()


def _safe_error_message(error: Exception) -> str:
    try:
        message = str(error)
    except Exception:
        message = "notification send failed"
    message = " ".join(message.split())
    message = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)
    message = _BEARER_VALUE.sub("Bearer [REDACTED]", message)
    if not message:
        message = "notification send failed"
    if len(message) > MAX_DISPATCH_ERROR_MESSAGE_LENGTH:
        message = message[: MAX_DISPATCH_ERROR_MESSAGE_LENGTH - 1] + "…"
    return message
