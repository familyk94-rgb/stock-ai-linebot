import importlib
import logging
import threading
from types import SimpleNamespace

import pytest

from services.providers import fubon_neo_client
from services.providers.fubon_neo_client import FubonNeoClientManager


BASE_ENV = {
    "FUBON_NEO_ENABLED": "true",
    "FUBON_USER_ID": "USER-ID-SECRET",
    "FUBON_PASSWORD": "PASSWORD-SECRET",
    "FUBON_CERT_PATH": "C:/secret/client.pfx",
    "FUBON_CERT_PASSWORD": "CERT-PASSWORD-SECRET",
}


class FakeSDK:
    def __init__(self, result=None):
        self.result = result or _success_result()
        self.login_calls = []
        self.logout_calls = 0
        self.disconnect_calls = 0

    def login(self, *args):
        self.login_calls.append(args)
        return self.result

    def logout(self):
        self.logout_calls += 1

    def disconnect(self):
        self.disconnect_calls += 1


def _stock_account(number="A123"):
    return SimpleNamespace(account=number, account_type="stock")


def _success_result(accounts=None):
    return SimpleNamespace(is_success=True, data=accounts or [_stock_account()])


def _manager(*, env=None, sdk=None, importer=None):
    sdk = sdk or FakeSDK()
    return FubonNeoClientManager(
        environ=BASE_ENV if env is None else env,
        sdk_factory=(lambda: sdk) if importer is None else None,
        module_importer=importer,
    ), sdk


def test_module_import_does_not_import_sdk_or_create_client(monkeypatch):
    real_import = importlib.import_module
    calls = []

    def capture(name, *args, **kwargs):
        calls.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", capture)
    importlib.reload(fubon_neo_client)
    assert "fubon_neo.sdk" not in calls
    assert fubon_neo_client._manager is None


def test_disabled_never_imports_creates_or_logs_in():
    calls = []
    manager = FubonNeoClientManager(
        environ={"FUBON_NEO_ENABLED": "false"},
        module_importer=lambda name: calls.append(name),
    )
    assert manager.ensure_login() is False
    assert calls == []
    assert manager.readiness() == {
        "enabled": False,
        "configured": False,
        "sdk_available": False,
        "logged_in": False,
        "status": "disabled",
        "reason": "disabled",
    }


def test_missing_configuration_does_not_import_sdk_or_log_secrets():
    calls = []
    manager = FubonNeoClientManager(
        environ={"FUBON_NEO_ENABLED": "true", "FUBON_USER_ID": "private"},
        module_importer=lambda name: calls.append(name),
    )
    assert manager.ensure_login() is False
    assert calls == []
    assert manager.readiness()["status"] == "not_configured"
    assert manager.readiness()["reason"] == "missing_configuration"
    assert "private" not in repr(manager.readiness())


def test_sdk_unavailable_is_degraded_without_import_crash():
    def unavailable(name):
        raise ModuleNotFoundError("sensitive module failure")

    manager = FubonNeoClientManager(environ=BASE_ENV, module_importer=unavailable)
    assert manager.ensure_login() is False
    assert manager.readiness() == {
        "enabled": True,
        "configured": True,
        "sdk_available": False,
        "logged_in": False,
        "status": "degraded",
        "reason": "sdk_not_installed",
    }


def test_login_success_is_lazy_and_reused():
    created = []
    sdk = FakeSDK()
    manager = FubonNeoClientManager(
        environ=BASE_ENV,
        sdk_factory=lambda: created.append(sdk) or sdk,
    )
    assert created == []
    assert manager.ensure_login() is True
    assert manager.ensure_login() is True
    assert manager.get_client() is sdk
    assert manager.get_account() is sdk.result.data[0]
    assert created == [sdk]
    assert len(sdk.login_calls) == 1
    assert manager.readiness()["status"] == "ready"


def test_concurrent_first_login_creates_and_logs_in_once():
    sdk = FakeSDK()
    manager, _ = _manager(sdk=sdk)
    barrier = threading.Barrier(8)
    results = []

    def worker():
        barrier.wait()
        results.append(manager.ensure_login())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [True] * 8
    assert len(sdk.login_calls) == 1


@pytest.mark.parametrize("failure", [RuntimeError("secret failure"), ValueError("bad")])
def test_login_exception_is_safe_and_not_retried(monkeypatch, failure):
    events = []

    class FailingSDK(FakeSDK):
        def login(self, *args):
            self.login_calls.append(args)
            raise failure

    sdk = FailingSDK()
    manager, _ = _manager(sdk=sdk)
    monkeypatch.setattr(fubon_neo_client, "log_event", lambda *a, **k: events.append(k))
    assert manager.ensure_login() is False
    assert manager.ensure_login() is False
    assert len(sdk.login_calls) == 1
    assert manager.readiness()["reason"] == "login_failed"
    assert len(events) == 1
    assert events[0]["error_type"] == type(failure).__name__
    assert "secret failure" not in repr(events)


def test_empty_accounts_are_rejected():
    sdk = FakeSDK(SimpleNamespace(is_success=True, data=[]))
    manager, _ = _manager(sdk=sdk)
    assert manager.ensure_login() is False
    assert manager.readiness()["reason"] == "no_stock_account"


def test_selects_first_stock_account_from_dict_and_attribute_objects():
    accounts = [
        {"account": "FUTURES", "account_type": "futures"},
        SimpleNamespace(account="STOCK", account_type="stock"),
    ]
    sdk = FakeSDK(_success_result(accounts))
    manager, _ = _manager(sdk=sdk)
    assert manager.ensure_login() is True
    assert manager.get_account().account == "STOCK"


def test_configured_account_number_selects_exact_stock_account():
    env = {**BASE_ENV, "FUBON_ACCOUNT_NO": "SECOND"}
    accounts = [_stock_account("FIRST"), {"account_no": "SECOND", "type": "stock"}]
    sdk = FakeSDK(_success_result(accounts))
    manager, _ = _manager(env=env, sdk=sdk)
    assert manager.ensure_login() is True
    assert manager.get_account()["account_no"] == "SECOND"


def test_missing_configured_account_is_safe_failure():
    env = {**BASE_ENV, "FUBON_ACCOUNT_NO": "MISSING"}
    manager, _ = _manager(env=env)
    assert manager.ensure_login() is False
    assert manager.readiness()["reason"] == "no_stock_account"


def test_ambiguous_untyped_accounts_are_not_guessed():
    sdk = FakeSDK(_success_result([{"account": "ONE"}, {"account": "TWO"}]))
    manager, _ = _manager(sdk=sdk)
    assert manager.ensure_login() is False
    assert manager.readiness()["reason"] == "no_stock_account"


def test_reconnect_reuses_sdk_and_performs_one_new_login():
    manager, sdk = _manager()
    assert manager.ensure_login() is True
    assert manager.reconnect() is True
    assert manager.readiness()["status"] == "ready"
    assert len(sdk.login_calls) == 2


def test_reconnect_failure_is_degraded_without_retry():
    sdk = FakeSDK()
    manager, _ = _manager(sdk=sdk)
    assert manager.ensure_login() is True
    sdk.result = SimpleNamespace(is_success=False, data=[])
    assert manager.reconnect() is False
    assert len(sdk.login_calls) == 2
    assert manager.readiness()["status"] == "degraded"


def test_shutdown_calls_available_methods_and_clears_state():
    manager, sdk = _manager()
    assert manager.ensure_login() is True
    manager.shutdown()
    assert sdk.logout_calls == 1
    assert sdk.disconnect_calls == 1
    assert manager.readiness()["logged_in"] is False
    assert manager.get_client() is None
    assert len(sdk.login_calls) == 1


def test_shutdown_without_cleanup_methods_is_noop():
    sdk = SimpleNamespace(login=lambda *args: _success_result())
    manager, _ = _manager(sdk=sdk)
    assert manager.ensure_login() is True
    manager.shutdown()
    assert manager.readiness()["logged_in"] is False


def test_shutdown_failure_is_swallowed_and_logged_once(monkeypatch):
    events = []
    manager, sdk = _manager()
    assert manager.ensure_login() is True
    sdk.logout = lambda: (_ for _ in ()).throw(RuntimeError("SECRET"))
    monkeypatch.setattr(fubon_neo_client, "log_event", lambda *a, **k: events.append(k))
    manager.shutdown()
    assert manager.readiness()["logged_in"] is False
    assert len(events) == 1
    assert events[0]["error_type"] == "RuntimeError"
    assert "SECRET" not in repr(events)


def test_logging_failure_never_changes_login_reconnect_or_shutdown(monkeypatch):
    monkeypatch.setattr(
        fubon_neo_client,
        "log_event",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("logging")),
    )
    sdk = FakeSDK(SimpleNamespace(is_success=False, data=[]))
    manager, _ = _manager(sdk=sdk)
    assert manager.ensure_login() is False
    assert manager.reconnect() is False
    manager.shutdown()
    assert manager.readiness()["logged_in"] is False


def test_readiness_and_repr_do_not_expose_secrets():
    manager, sdk = _manager()
    assert manager.ensure_login() is True
    text = repr(manager.readiness())
    for secret in BASE_ENV.values():
        assert secret not in text
    assert sdk.result.data[0].account not in text


def test_process_singleton_is_lazy(monkeypatch):
    monkeypatch.setattr(fubon_neo_client, "_manager", None)
    first = fubon_neo_client.get_fubon_neo_client_manager()
    second = fubon_neo_client.get_fubon_neo_client_manager()
    assert first is second
    assert first.readiness()["sdk_available"] is False
