from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from core.models.alert_trigger import AlertTrigger
from core.models.dispatch_result import DispatchItemResult, DispatchReport
from core.models.notification_event import NotificationEvent


TRIGGERED_AT = "2026-07-17T12:00:00+08:00"


def _event(**overrides):
    values = {
        "alert_id": 1,
        "recipient_id": "user-1",
        "stock_id": "2330",
        "condition": "GT",
        "target_price": Decimal("1000"),
        "current_price": Decimal("1001"),
        "triggered_at": TRIGGERED_AT,
    }
    values.update(overrides)
    return NotificationEvent(**values)


def test_notification_event_is_frozen_slotted_and_valid():
    event = _event()
    assert event.target_price == Decimal("1000")
    assert event.current_price == Decimal("1001")
    assert not hasattr(event, "__dict__")
    with pytest.raises(FrozenInstanceError):
        event.stock_id = "2454"


@pytest.mark.parametrize("alert_id", [0, -1, True, False, 1.0, "1"])
def test_notification_event_rejects_invalid_alert_id(alert_id):
    with pytest.raises(ValueError):
        _event(alert_id=alert_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipient_id", ""),
        ("recipient_id", "  "),
        ("stock_id", ""),
        ("stock_id", None),
        ("condition", "GE"),
        ("condition", "gt"),
    ],
)
def test_notification_event_rejects_invalid_text_fields(field, value):
    with pytest.raises(ValueError):
        _event(**{field: value})


@pytest.mark.parametrize("field", ["target_price", "current_price"])
def test_notification_event_rejects_float_price(field):
    with pytest.raises(TypeError):
        _event(**{field: 1000.0})


@pytest.mark.parametrize(
    "price",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), Decimal("0"), Decimal("-1")],
)
@pytest.mark.parametrize("field", ["target_price", "current_price"])
def test_notification_event_rejects_nonpositive_or_nonfinite_decimal(field, price):
    with pytest.raises(ValueError):
        _event(**{field: price})


@pytest.mark.parametrize(
    "triggered_at",
    ["", "not-a-date", "2026-07-17T12:00:00", "2026-07-17"],
)
def test_notification_event_requires_timezone_aware_iso(triggered_at):
    with pytest.raises(ValueError):
        _event(triggered_at=triggered_at)


def test_notification_event_converts_from_alert_trigger_without_mutation():
    trigger = AlertTrigger(
        alert_id=7,
        line_user_id="line-user",
        stock_id="2454",
        condition="LT",
        target_price=Decimal("1200"),
        current_price=Decimal("1199"),
        triggered_at=TRIGGERED_AT,
    )
    event = NotificationEvent.from_alert_trigger(trigger)

    assert event == NotificationEvent(
        alert_id=7,
        recipient_id="line-user",
        stock_id="2454",
        condition="LT",
        target_price=trigger.target_price,
        current_price=trigger.current_price,
        triggered_at=trigger.triggered_at,
    )
    assert event.target_price is trigger.target_price
    assert event.current_price is trigger.current_price
    assert event.recipient_id == trigger.line_user_id
    assert not any(value is trigger for value in (
        event.alert_id, event.recipient_id, event.stock_id, event.condition,
        event.target_price, event.current_price, event.triggered_at,
    ))


def test_notification_event_factory_rejects_other_types():
    with pytest.raises(TypeError):
        NotificationEvent.from_alert_trigger({})


def test_dispatch_item_result_success_and_failure_invariants():
    success = DispatchItemResult(1, "user-1", "test", True)
    failure = DispatchItemResult(2, "user-2", "test", False, "RuntimeError", "failed")
    assert success.error_type is None
    assert failure.error_type == "RuntimeError"
    assert not hasattr(success, "__dict__")
    with pytest.raises(FrozenInstanceError):
        success.success = False
    with pytest.raises(ValueError):
        DispatchItemResult(1, "user-1", "test", True, "Error", "failed")
    with pytest.raises(ValueError):
        DispatchItemResult(1, "user-1", "test", False)
    with pytest.raises(ValueError):
        DispatchItemResult(1, "user-1", "test", False, "Error", "x" * 161)


def test_dispatch_report_invariants_and_immutable_tuple_results():
    result = DispatchItemResult(1, "user-1", "test", True)
    report = DispatchReport("test", 1, 1, 0, (result,))
    assert report.results == (result,)
    assert not hasattr(report, "__dict__")
    with pytest.raises(FrozenInstanceError):
        report.failed = 1
    with pytest.raises(ValueError):
        DispatchReport("test", 1, 0, 0, (result,))
    with pytest.raises(ValueError):
        DispatchReport("test", 2, 1, 1, (result,))
    with pytest.raises(ValueError):
        DispatchReport("other", 1, 1, 0, (result,))
    failure = DispatchItemResult(2, "user-2", "test", False, "Error", "failed")
    with pytest.raises(ValueError):
        DispatchReport("test", 1, 1, 0, (failure,))
    with pytest.raises(ValueError):
        DispatchReport("test", 1, 0, 1, (result,))
    with pytest.raises(TypeError):
        DispatchReport("test", 1, 1, 0, [result])


@pytest.mark.parametrize(
    ("attempted", "succeeded", "failed"),
    [(-1, 0, 0), (0, -1, 1), (0, 0, -1), (True, 1, 0)],
)
def test_dispatch_report_rejects_invalid_counts(attempted, succeeded, failed):
    with pytest.raises(ValueError):
        DispatchReport("test", attempted, succeeded, failed, ())
