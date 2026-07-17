"""Process-local lifecycle manager for the optional Fubon Neo SDK.

The module intentionally does not import ``fubon_neo`` at import time.  Neo is
not part of the market-data path yet; this manager only owns configuration,
login state, account selection, reconnect, readiness and shutdown.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Mapping
from typing import Any, Callable

from core.observability import log_event


logger = logging.getLogger(__name__)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_REQUIRED_NON_EMPTY_ENV = (
    "FUBON_USER_ID",
    "FUBON_PASSWORD",
    "FUBON_CERT_PATH",
)
_ACCOUNT_NUMBER_FIELDS = (
    "account",
    "account_no",
    "account_number",
    "accountNo",
)
_ACCOUNT_TYPE_FIELDS = (
    "account_type",
    "accountType",
    "market_type",
    "marketType",
    "type",
)
_STOCK_ACCOUNT_TYPES = frozenset(
    {"stock", "stocks", "equity", "securities", "證券", "股票"}
)
_SAFE_REASONS = frozenset(
    {
        "disabled",
        "missing_configuration",
        "sdk_not_installed",
        "login_failed",
        "no_stock_account",
        "ready",
    }
)


class FubonNeoClientManager:
    """Own one lazy Fubon SDK session per Python process."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        sdk_factory: Callable[[], Any] | None = None,
        module_importer: Callable[[str], Any] | None = None,
    ) -> None:
        self._environ = environ if environ is not None else os.environ
        self._sdk_factory = sdk_factory
        self._module_importer = module_importer or importlib.import_module
        self._lock = threading.RLock()
        self._sdk: Any | None = None
        self._account: Any | None = None
        self._logged_in = False
        self._login_attempted = False
        self._sdk_available = False
        self._shutdown = False
        self._status, self._reason = self._initial_state()

    def ensure_login(self) -> bool:
        """Lazily create the SDK and perform at most one login attempt."""
        with self._lock:
            if self._logged_in:
                return True
            if self._shutdown:
                self._set_degraded("login_failed")
                return False
            if not self._enabled():
                self._set_state("disabled", "disabled")
                return False
            if not self._configured():
                self._set_state("not_configured", "missing_configuration")
                self._safe_event("configuration", "missing_configuration")
                return False
            if self._login_attempted:
                return False

            self._login_attempted = True
            try:
                sdk = self._get_or_create_sdk()
            except (ImportError, ModuleNotFoundError) as error:
                self._set_degraded("sdk_not_installed")
                self._safe_event("sdk_import", "sdk_not_installed", error)
                return False
            except Exception as error:
                self._set_degraded("login_failed")
                self._safe_event("sdk_create", "login_failed", error)
                return False

            try:
                user_id = self._value("FUBON_USER_ID")
                password = self._value("FUBON_PASSWORD")
                cert_path = self._value("FUBON_CERT_PATH")
                cert_password = self._value("FUBON_CERT_PASSWORD")
                if cert_password:
                    result = sdk.login(
                        user_id,
                        password,
                        cert_path,
                        cert_password,
                    )
                else:
                    result = sdk.login(user_id, password, cert_path)
                if _field(result, "is_success") is not True:
                    self._set_degraded("login_failed")
                    self._safe_event("login", "login_failed")
                    return False
                account = self._select_account(_field(result, "data"))
                if account is None:
                    self._set_degraded("no_stock_account")
                    self._safe_event("login", "no_stock_account")
                    return False
            except Exception as error:
                self._set_degraded("login_failed")
                self._safe_event("login", "login_failed", error)
                return False

            self._account = account
            self._logged_in = True
            self._set_state("ready", "ready")
            return True

    def get_client(self) -> Any | None:
        """Return the logged-in SDK instance, otherwise ``None``."""
        return self._sdk if self.ensure_login() else None

    def get_account(self) -> Any | None:
        """Return the selected stock account without exposing it in logs."""
        return self._account if self.ensure_login() else None

    def reconnect(self) -> bool:
        """Reset session state and perform exactly one controlled login."""
        with self._lock:
            if not self._enabled():
                self._set_state("disabled", "disabled")
                return False
            self._logged_in = False
            self._account = None
            self._login_attempted = False
            self._shutdown = False
            success = self.ensure_login()
            if not success:
                self._safe_event("reconnect", self._reason)
            return success

    def shutdown(self) -> None:
        """Best-effort SDK cleanup; missing cleanup methods are valid."""
        with self._lock:
            sdk = self._sdk
            if sdk is not None:
                for method_name in ("logout", "disconnect"):
                    method = getattr(sdk, method_name, None)
                    if not callable(method):
                        continue
                    try:
                        method()
                    except Exception as error:
                        self._safe_event("shutdown", "login_failed", error)
            self._logged_in = False
            self._account = None
            self._shutdown = True
            if self._enabled() and self._configured():
                self._set_degraded("login_failed")
            else:
                self._status, self._reason = self._initial_state()

    def readiness(self) -> dict[str, Any]:
        """Return a fixed, secret-free health contract."""
        with self._lock:
            return {
                "enabled": self._enabled(),
                "configured": self._configured(),
                "sdk_available": bool(self._sdk_available),
                "logged_in": bool(self._logged_in),
                "status": self._status,
                "reason": self._reason,
            }

    def _initial_state(self) -> tuple[str, str]:
        if not self._enabled():
            return "disabled", "disabled"
        if not self._configured():
            return "not_configured", "missing_configuration"
        return "degraded", "login_failed"

    def _enabled(self) -> bool:
        return self._value("FUBON_NEO_ENABLED").casefold() in _TRUE_VALUES

    def _configured(self) -> bool:
        return (
            all(self._value(name) for name in _REQUIRED_NON_EMPTY_ENV)
            and self._environ.get("FUBON_CERT_PASSWORD") is not None
        )

    def _value(self, name: str) -> str:
        value = self._environ.get(name, "")
        return value.strip() if isinstance(value, str) else ""

    def _get_or_create_sdk(self) -> Any:
        if self._sdk is not None:
            return self._sdk
        factory = self._sdk_factory
        if factory is None:
            module = self._module_importer("fubon_neo.sdk")
            factory = getattr(module, "FubonSDK")
        self._sdk = factory()
        self._sdk_available = True
        return self._sdk

    def _select_account(self, raw_accounts: Any) -> Any | None:
        accounts = _account_list(raw_accounts)
        if not accounts:
            return None

        requested = self._value("FUBON_ACCOUNT_NO")
        if requested:
            for account in accounts:
                if _account_number(account) == requested and _is_stock_account(account):
                    return account
            return None

        stock_accounts = [account for account in accounts if _is_stock_account(account)]
        if stock_accounts:
            return stock_accounts[0]

        # Some SDK versions expose only one securities account without an
        # account-type field.  A single account is accepted; ambiguous lists
        # are rejected instead of guessing.
        return accounts[0] if len(accounts) == 1 and not _has_account_type(accounts[0]) else None

    def _set_state(self, status: str, reason: str) -> None:
        self._status = status
        self._reason = reason if reason in _SAFE_REASONS else "login_failed"

    def _set_degraded(self, reason: str) -> None:
        self._logged_in = False
        self._account = None
        self._set_state("degraded", reason)

    def _safe_event(
        self, operation: str, reason: str, error: BaseException | None = None
    ) -> None:
        try:
            log_event(
                logger,
                "service_fallback",
                result="fallback",
                service="fubon_neo",
                operation=operation,
                reason=reason if reason in _SAFE_REASONS else "login_failed",
                error_type=type(error).__name__ if error is not None else None,
            )
        except Exception:
            pass


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _account_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    nested = _field(value, "accounts")
    return list(nested) if isinstance(nested, (list, tuple)) else []


def _account_number(account: Any) -> str:
    for field in _ACCOUNT_NUMBER_FIELDS:
        value = _field(account, field)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            return str(value).strip()
    return ""


def _has_account_type(account: Any) -> bool:
    return any(_field(account, field) is not None for field in _ACCOUNT_TYPE_FIELDS)


def _is_stock_account(account: Any) -> bool:
    for field in _ACCOUNT_TYPE_FIELDS:
        value = _field(account, field)
        if isinstance(value, str) and value.strip().casefold() in _STOCK_ACCOUNT_TYPES:
            return True
    return False


_manager_lock = threading.Lock()
_manager: FubonNeoClientManager | None = None


def get_fubon_neo_client_manager() -> FubonNeoClientManager:
    """Return the process-local manager without importing or creating SDK."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = FubonNeoClientManager()
    return _manager
