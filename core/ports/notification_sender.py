"""Port implemented by notification delivery adapters."""

from typing import Protocol

from core.models.notification_event import NotificationEvent


class NotificationSender(Protocol):
    @property
    def channel(self) -> str:
        ...

    def send(self, event: NotificationEvent) -> None:
        ...
