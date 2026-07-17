from copy import deepcopy
from decimal import Decimal

import pytest

from core.models.dispatch_result import DispatchItemResult, DispatchReport
from core.models.notification_event import NotificationEvent
from core.notification_dispatcher import (
    DuplicateNotificationChannelError,
    InvalidNotificationChannelError,
    NotificationDispatcher,
    UnknownNotificationChannelError,
)


def _event(alert_id=1):
    return NotificationEvent(
        alert_id=alert_id,
        recipient_id=f"user-{alert_id}",
        stock_id="2330",
        condition="GT",
        target_price=Decimal("1000"),
        current_price=Decimal("1001"),
        triggered_at="2026-07-17T12:00:00+08:00",
    )


class FakeSender:
    def __init__(self, channel="test"):
        self._channel = channel
        self.sent = []

    @property
    def channel(self):
        return self._channel

    def send(self, event):
        self.sent.append(event)


class SelectiveFailSender(FakeSender):
    def __init__(self, failures, *, error=None):
        super().__init__()
        self.failures = set(failures)
        self.error = error or RuntimeError("simulated failure")

    def send(self, event):
        self.sent.append(event)
        if event.alert_id in self.failures:
            raise self.error


def test_sender_registry_accepts_one_and_multiple_channels():
    first = FakeSender("first")
    second = FakeSender("second")
    dispatcher = NotificationDispatcher([first, second])
    assert dispatcher.dispatch([_event()], channel="second").succeeded == 1
    assert first.sent == []
    assert second.sent == [_event()]


def test_duplicate_and_blank_sender_channels_are_rejected():
    with pytest.raises(DuplicateNotificationChannelError):
        NotificationDispatcher([FakeSender("test"), FakeSender(" test ")])
    with pytest.raises(InvalidNotificationChannelError):
        NotificationDispatcher([FakeSender("  ")])


def test_unknown_or_blank_dispatch_channel_is_rejected():
    dispatcher = NotificationDispatcher([FakeSender()])
    with pytest.raises(UnknownNotificationChannelError):
        dispatcher.dispatch([], channel="missing")
    with pytest.raises(InvalidNotificationChannelError):
        dispatcher.dispatch([], channel=" ")


def test_empty_events_returns_empty_report_without_sender_call():
    sender = FakeSender()
    report = NotificationDispatcher([sender]).dispatch([], channel="test")
    assert report == DispatchReport("test", 0, 0, 0, ())
    assert sender.sent == []


def test_single_and_multiple_success_preserve_order_and_call_once():
    sender = FakeSender()
    events = [_event(1), _event(2), _event(3)]
    original = list(events)
    report = NotificationDispatcher([sender]).dispatch(events, channel="test")

    assert report.attempted == report.succeeded == 3
    assert report.failed == 0
    assert [result.alert_id for result in report.results] == [1, 2, 3]
    assert all(result.success for result in report.results)
    assert sender.sent == events
    assert events == original


def test_partial_failure_continues_and_records_safe_result():
    sender = SelectiveFailSender({2})
    report = NotificationDispatcher([sender]).dispatch(
        [_event(1), _event(2), _event(3)], channel="test"
    )
    assert (report.attempted, report.succeeded, report.failed) == (3, 2, 1)
    assert [result.success for result in report.results] == [True, False, True]
    assert report.results[1].error_type == "RuntimeError"
    assert report.results[1].error_message == "simulated failure"
    assert sender.sent == [_event(1), _event(2), _event(3)]


def test_all_failures_are_results_not_batch_exception():
    sender = SelectiveFailSender({1, 2})
    report = NotificationDispatcher([sender]).dispatch(
        [_event(1), _event(2)], channel="test"
    )
    assert report.succeeded == 0
    assert report.failed == 2
    assert all(not result.success for result in report.results)


def test_dispatcher_is_reusable_without_result_accumulation():
    sender = FakeSender()
    dispatcher = NotificationDispatcher([sender])
    first = dispatcher.dispatch([_event(1), _event(2)], channel="test")
    second = dispatcher.dispatch([_event(3)], channel="test")
    assert first.attempted == 2
    assert second.attempted == 1
    assert [item.alert_id for item in second.results] == [3]


def test_dispatch_does_not_modify_events_or_input_list():
    sender = FakeSender()
    events = [_event(1), _event(2)]
    original = deepcopy(events)
    NotificationDispatcher([sender]).dispatch(events, channel="test")
    assert events == original


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_base_exceptions_are_not_caught(error):
    class BaseExceptionSender(FakeSender):
        def send(self, event):
            raise error

    with pytest.raises(type(error)):
        NotificationDispatcher([BaseExceptionSender()]).dispatch(
            [_event()], channel="test"
        )


def test_error_message_is_redacted_and_length_limited():
    secret = "TOP-SECRET-VALUE"
    error = RuntimeError(
        f"access_token={secret} reply_token=reply-secret request_headers=private "
        "authorization:BearerValue password=hunter2 "
        + "x" * 300
    )
    report = NotificationDispatcher(
        [SelectiveFailSender({1}, error=error)]
    ).dispatch([_event()], channel="test")
    result = report.results[0]
    assert len(result.error_message) <= 160
    assert secret not in result.error_message
    assert "hunter2" not in result.error_message
    assert "BearerValue" not in result.error_message
    assert "reply-secret" not in result.error_message
    assert "private" not in result.error_message
    assert not hasattr(result, "exception")


def test_exception_string_failure_is_safely_handled():
    class BrokenStringError(Exception):
        def __str__(self):
            raise RuntimeError("cannot stringify")

    report = NotificationDispatcher(
        [SelectiveFailSender({1}, error=BrokenStringError())]
    ).dispatch([_event()], channel="test")
    assert report.results[0].error_message == "notification send failed"


def test_generator_input_is_supported_and_normalized_once():
    sender = FakeSender()
    report = NotificationDispatcher([sender]).dispatch(
        (_event(value) for value in (1, 2)), channel="test"
    )
    assert report.attempted == 2
    assert isinstance(report.results, tuple)


def test_non_event_input_is_rejected_before_any_send():
    sender = FakeSender()
    with pytest.raises(TypeError):
        NotificationDispatcher([sender]).dispatch([_event(), {}], channel="test")
    assert sender.sent == []


def test_dispatch_results_do_not_store_sender_or_exception_objects():
    sender = SelectiveFailSender({1})
    report = NotificationDispatcher([sender]).dispatch([_event()], channel="test")
    result = report.results[0]
    assert isinstance(result, DispatchItemResult)
    assert set(result.__slots__) == {
        "alert_id", "recipient_id", "channel", "success", "error_type", "error_message"
    }
