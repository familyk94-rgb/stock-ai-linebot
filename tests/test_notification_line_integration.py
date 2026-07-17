from decimal import Decimal

from adapters.notifications.line_push_sender import LinePushSender
from core.models.notification_event import NotificationEvent
from core.notification_dispatcher import NotificationDispatcher


class SelectiveMessagingApi:
    def __init__(self, failed_recipients=()):
        self.requests = []
        self.failed_recipients = set(failed_recipients)

    def push_message(self, request):
        self.requests.append(request)
        if request.to in self.failed_recipients:
            raise RuntimeError(
                f"Authorization: Bearer secret-token recipient={request.to}"
            )


class OtherSender:
    channel = "other"

    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)


def _event(alert_id=1, recipient_id="U1"):
    return NotificationEvent(
        alert_id=alert_id,
        recipient_id=recipient_id,
        stock_id="2330",
        condition="GT",
        target_price=Decimal("1000"),
        current_price=Decimal("1005"),
        triggered_at="2026-07-17T18:24:00+08:00",
    )


def test_dispatcher_line_success_contract_and_sender_selection():
    api = SelectiveMessagingApi()
    other = OtherSender()
    dispatcher = NotificationDispatcher([LinePushSender(api), other])

    report = dispatcher.dispatch([_event()], channel="line")

    assert (report.attempted, report.succeeded, report.failed) == (1, 1, 0)
    assert report.results[0].success is True
    assert len(api.requests) == 1
    assert other.events == []


def test_dispatcher_converts_line_failure_and_continues_in_order():
    api = SelectiveMessagingApi({"U2"})
    events = [_event(1, "U1"), _event(2, "U2"), _event(3, "U3")]
    before = tuple(events)

    report = NotificationDispatcher([LinePushSender(api)]).dispatch(
        events, channel="line"
    )

    assert (report.attempted, report.succeeded, report.failed) == (3, 2, 1)
    assert [item.alert_id for item in report.results] == [1, 2, 3]
    assert [item.success for item in report.results] == [True, False, True]
    failed = report.results[1]
    assert failed.error_type == "LinePushError"
    assert failed.error_message == "LINE push message failed: RuntimeError"
    assert "secret-token" not in failed.error_message
    assert "Authorization" not in failed.error_message
    assert "U2" not in failed.error_message
    assert [request.to for request in api.requests] == ["U1", "U2", "U3"]
    assert tuple(events) == before


def test_empty_dispatch_does_not_call_line_api():
    api = SelectiveMessagingApi()

    report = NotificationDispatcher([LinePushSender(api)]).dispatch(
        [], channel="line"
    )

    assert (report.attempted, report.succeeded, report.failed) == (0, 0, 0)
    assert report.results == ()
    assert api.requests == []


def test_each_recipient_receives_a_separate_push_request():
    api = SelectiveMessagingApi()
    events = [_event(1, "U1"), _event(2, "U2")]

    report = NotificationDispatcher([LinePushSender(api)]).dispatch(
        events, channel="line"
    )

    assert report.succeeded == 2
    assert len(api.requests) == 2
    assert [request.to for request in api.requests] == ["U1", "U2"]
