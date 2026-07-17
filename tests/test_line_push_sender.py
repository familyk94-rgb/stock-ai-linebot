from dataclasses import asdict
from decimal import Decimal

import pytest
from linebot.v3.messaging import PushMessageRequest, TextMessage

from adapters.notifications.line_push_sender import (
    MAX_LINE_ALERT_MESSAGE_LENGTH,
    LinePushError,
    LinePushSender,
    format_line_alert_message,
)
from core.models.alert_trigger import AlertTrigger
from core.models.notification_event import NotificationEvent


class FakeMessagingApi:
    def __init__(self):
        self.requests = []

    def push_message(self, request):
        self.requests.append(request)


def _event(**overrides):
    values = {
        "alert_id": 1,
        "recipient_id": "U123456",
        "stock_id": "2330",
        "condition": "GT",
        "target_price": Decimal("1000"),
        "current_price": Decimal("1005"),
        "triggered_at": "2026-07-17T10:24:00+00:00",
    }
    values.update(overrides)
    return NotificationEvent(**values)


def test_gt_message_has_exact_contract():
    message = format_line_alert_message(_event())

    assert message == (
        "股市柑仔店｜價格提醒\n\n"
        "股票：2330\n"
        "條件：高於 1,000 元\n"
        "目前價格：1,005 元\n"
        "觸發時間：2026-07-17 18:24\n\n"
        "價格已高於設定提醒價。"
    )
    assert "U123456" not in message
    assert "alert_id" not in message
    assert "GT" not in message


def test_lt_message_has_exact_contract():
    message = format_line_alert_message(
        _event(
            condition="LT",
            target_price=Decimal("900"),
            current_price=Decimal("895"),
        )
    )

    assert message == (
        "股市柑仔店｜價格提醒\n\n"
        "股票：2330\n"
        "條件：低於 900 元\n"
        "目前價格：895 元\n"
        "觸發時間：2026-07-17 18:24\n\n"
        "價格已低於設定提醒價。"
    )
    assert "LT" not in message


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1000"), "1,000"),
        (Decimal("1000.0"), "1,000"),
        (Decimal("1000.50"), "1,000.5"),
        (Decimal("895.25"), "895.25"),
        (Decimal("0.123400"), "0.1234"),
        (Decimal("1E+6"), "1,000,000"),
    ],
)
def test_decimal_format_is_exact_without_float_or_scientific_notation(value, expected):
    message = format_line_alert_message(_event(target_price=value))
    assert f"條件：高於 {expected} 元" in message
    assert "E+" not in message


def test_plus_eight_time_is_preserved_and_formatter_does_not_mutate_event():
    event = _event(triggered_at="2026-07-17T18:24:00+08:00")
    before = asdict(event)

    message = format_line_alert_message(event)

    assert "觸發時間：2026-07-17 18:24" in message
    assert asdict(event) == before
    assert 0 < len(message) <= MAX_LINE_ALERT_MESSAGE_LENGTH


def test_message_over_limit_is_rejected_without_truncation():
    event = _event(stock_id="1" * MAX_LINE_ALERT_MESSAGE_LENGTH)
    with pytest.raises(LinePushError, match="length is invalid"):
        format_line_alert_message(event)


@pytest.mark.parametrize("value", [None, {}, object()])
def test_formatter_rejects_non_notification_event(value):
    with pytest.raises(TypeError, match="NotificationEvent"):
        format_line_alert_message(value)


def test_sender_channel_and_push_request_contract():
    api = FakeMessagingApi()
    sender = LinePushSender(api)
    event = _event()

    result = sender.send(event)

    assert sender.channel == "line"
    assert result is None
    assert len(api.requests) == 1
    request = api.requests[0]
    assert isinstance(request, PushMessageRequest)
    assert request.to == event.recipient_id
    assert len(request.messages) == 1
    assert isinstance(request.messages[0], TextMessage)
    assert request.messages[0].text == format_line_alert_message(event)
    assert not hasattr(api, "reply_message")


@pytest.mark.parametrize("api", [None, object(), type("Api", (), {"push_message": 1})()])
def test_sender_rejects_invalid_messaging_api(api):
    with pytest.raises(TypeError, match="callable push_message"):
        LinePushSender(api)


@pytest.mark.parametrize("value", [None, {}, object()])
def test_sender_rejects_non_notification_event_without_calling_api(value):
    api = FakeMessagingApi()
    sender = LinePushSender(api)
    with pytest.raises(TypeError, match="NotificationEvent"):
        sender.send(value)
    assert api.requests == []


def test_sender_rejects_alert_trigger_without_calling_api():
    api = FakeMessagingApi()
    trigger = AlertTrigger(
        alert_id=1,
        line_user_id="U123456",
        stock_id="2330",
        condition="GT",
        target_price=Decimal("1000"),
        current_price=Decimal("1005"),
        triggered_at="2026-07-17T18:24:00+08:00",
    )
    with pytest.raises(TypeError, match="NotificationEvent"):
        LinePushSender(api).send(trigger)
    assert api.requests == []


def test_sdk_exception_is_converted_to_safe_line_push_error():
    class FailingApi:
        def push_message(self, request):
            raise RuntimeError(
                "Authorization: Bearer secret-token recipient=U123456"
            )

    with pytest.raises(LinePushError) as captured:
        LinePushSender(FailingApi()).send(_event())

    message = str(captured.value)
    assert message == "LINE push message failed: RuntimeError"
    assert "secret-token" not in message
    assert "Authorization" not in message
    assert "U123456" not in message
    assert isinstance(captured.value.__cause__, RuntimeError)


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_sender_does_not_catch_base_exception(error):
    class InterruptingApi:
        def push_message(self, request):
            raise error

    with pytest.raises(type(error)):
        LinePushSender(InterruptingApi()).send(_event())


def test_sender_is_reusable_and_does_not_retain_events():
    api = FakeMessagingApi()
    sender = LinePushSender(api)
    first = _event(alert_id=1, recipient_id="U1")
    second = _event(alert_id=2, recipient_id="U2", stock_id="2454")

    sender.send(first)
    sender.send(second)

    assert [request.to for request in api.requests] == ["U1", "U2"]
    assert set(vars(sender)) == {"_messaging_api"}
