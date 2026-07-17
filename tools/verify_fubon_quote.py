"""Verify the production Fubon Neo REST quote schema safely.

Run this only in an environment where the FUBON_* secrets are configured.
The tool never prints credentials, account details, raw responses or exception
messages.  A fixture is written only after a successful quote response.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.providers.fubon_neo_client import get_fubon_neo_client_manager
from services.providers.fubon_neo_quote import FIELD_ALIASES, adapt_quote


SDK_METHOD = "marketdata.rest_client.stock.intraday.quote"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "fubon_neo"
    / "production_quote_sample.json"
)
_SENSITIVE_KEY_PARTS = (
    "account", "authorization", "cert", "client", "cookie", "credential",
    "identity", "passwd", "password", "secret", "session", "token",
    "user_id", "userid",
)
_SENSITIVE_EXACT_KEYS = frozenset({"id"})
_WRAPPER_KEYS = ("success", "error", "data")
_DISPLAY_FIELDS = (
    "symbol", "price", "reference", "change", "change_percent", "open",
    "high", "low", "volume", "status", "market", "timestamp", "is_realtime",
)
_FLAT_QUOTE_EVIDENCE_FIELDS = frozenset(
    {
        *FIELD_ALIASES["price"],
        *FIELD_ALIASES["reference"],
        *FIELD_ALIASES["open"],
        *FIELD_ALIASES["volume"],
        *FIELD_ALIASES["timestamp"],
        "total",
        "lastUpdated",
    }
)
_SAFE_QUOTE_FIELDS = frozenset(
    {
        *(alias for aliases in FIELD_ALIASES.values() for alias in aliases),
        "amplitude",
        "asks",
        "avgPrice",
        "bids",
        "closeTime",
        "date",
        "highTime",
        "isClose",
        "lastSize",
        "lastTrade",
        "lastTrial",
        "lastUpdated",
        "lowTime",
        "name",
        "openTime",
        "serial",
        "total",
        "type",
    }
)
_REQUIRED_NON_EMPTY_ENV = (
    "FUBON_NEO_ENABLED",
    "FUBON_USER_ID",
    "FUBON_PASSWORD",
    "FUBON_CERT_PATH",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Fubon Neo quote schema")
    parser.add_argument("symbol", nargs="?", default="2330")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    load_dotenv(PROJECT_ROOT / ".env")
    if _missing_configuration(os.environ):
        print("verification=blocked reason=missing_configuration")
        return 2
    preflight_reason = _credential_preflight()
    if preflight_reason is not None:
        print(f"verification=blocked reason={preflight_reason}")
        return 2

    manager = get_fubon_neo_client_manager()
    client = manager.get_client()
    if client is None:
        readiness = manager.readiness()
        print(f"verification=blocked reason={readiness.get('reason', 'login_failed')}")
        return 2

    _initialize_realtime_if_available(client)
    try:
        response = client.marketdata.rest_client.stock.intraday.quote(
            symbol=args.symbol
        )
    except Exception as error:
        print(f"verification=failed error_type={type(error).__name__}")
        return 3

    wrapper, data, schema = _extract_quote_payload(response)
    _print_report(response, wrapper, data)

    if not data or (schema == "wrapper" and wrapper.get("success") is not True):
        print("fixture_written=false reason=quote_unsuccessful_or_empty")
        return 4

    adapter_result = adapt_quote(data, expected_symbol=args.symbol)
    print(f"adapter_ok={str(adapter_result.ok).lower()}")
    print(f"adapter_reason={adapter_result.reason}")
    if adapter_result.quote is not None:
        for key, value in adapter_result.quote.to_dict().items():
            print(f"adapter_quote_{key}={_safe_public_value(value)}")

    _write_fixture(args.output, wrapper, data, schema)
    print(f"fixture_written=true path={args.output.as_posix()}")
    return 0


def _initialize_realtime_if_available(client: Any) -> None:
    method = getattr(client, "init_realtime", None)
    if not callable(method):
        print("realtime_initialization=not_required_or_unavailable")
        return
    try:
        method()
        print("realtime_initialization=success")
    except Exception as error:
        print(f"realtime_initialization=fallback error_type={type(error).__name__}")


def _credential_preflight() -> str | None:
    certificate = os.environ.get("FUBON_CERT_PATH", "")
    if not isinstance(certificate, str) or not certificate.strip():
        return None
    try:
        certificate_path = Path(certificate.strip()).expanduser().resolve()
        if not certificate_path.is_file():
            return "certificate_file_unavailable"
        certificate_path.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None
    except Exception:
        return "certificate_file_unavailable"

    try:
        relative_path = certificate_path.relative_to(PROJECT_ROOT.resolve())
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(relative_path)],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=False,
            timeout=5,
        )
    except Exception:
        return "certificate_git_safety_unverified"
    return None if result.returncode == 0 else "certificate_path_not_git_ignored"


def _missing_configuration(environ: Mapping[str, str]) -> bool:
    for name in _REQUIRED_NON_EMPTY_ENV:
        value = environ.get(name)
        if not isinstance(value, str) or not value.strip():
            return True
    return environ.get("FUBON_CERT_PASSWORD") is None


def _extract_quote_payload(
    response: Any,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    mapping = _public_mapping(response)
    nested = mapping.get("data")
    if isinstance(nested, Mapping):
        return mapping, _public_mapping(nested), "wrapper"
    if _is_flat_quote_payload(mapping):
        return {}, mapping, "flat"
    return mapping, {}, "invalid"


def _is_flat_quote_payload(value: Mapping[str, Any]) -> bool:
    symbol = value.get("symbol")
    return bool(
        isinstance(symbol, str)
        and symbol.strip()
        and _FLAT_QUOTE_EVIDENCE_FIELDS.intersection(value)
    )


def _write_fixture(
    output: Path,
    wrapper: Mapping[str, Any],
    data: Mapping[str, Any],
    schema: str,
) -> None:
    payload = _sanitize_quote_payload(data)
    if schema == "wrapper":
        sample: dict[str, Any] = {
            "success": wrapper.get("success") is True,
            "error": None,
            "data": payload,
        }
    else:
        sample = payload
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(sample, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sanitize_quote_payload(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _sanitize(value)
        for key, value in data.items()
        if key in _SAFE_QUOTE_FIELDS and _safe_key(key)
    }


def _safe_public_value(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)):
        return str(value)[:128]
    return f"<{type(value).__name__}>"


def _print_report(response: Any, wrapper: Mapping[str, Any], data: Mapping[str, Any]) -> None:
    wrapper_keys = _safe_keys(wrapper)
    data_keys = _safe_keys(data)
    present_keys = set(data)
    known_aliases = {alias for aliases in FIELD_ALIASES.values() for alias in aliases}
    missing = [name for name, aliases in FIELD_ALIASES.items() if not present_keys.intersection(aliases)]
    unused = sorted(known_aliases - present_keys)
    unknown = sorted(key for key in present_keys - known_aliases if _safe_key(key))

    print(f"sdk_method={SDK_METHOD}")
    print(f"response_type={type(response).__name__}")
    print(f"response_wrapper_keys={','.join(wrapper_keys) or 'none'}")
    print(f"data_keys={','.join(data_keys) or 'none'}")
    for field in _DISPLAY_FIELDS:
        value = _display_value(data, FIELD_ALIASES[field])
        print(f"{field}={value}")
    print(f"timestamp_format={_timestamp_format(_first_value(data, FIELD_ALIASES['timestamp']))}")
    print(f"timestamp_timezone={_timestamp_timezone(_first_value(data, FIELD_ALIASES['timestamp']))}")
    print(f"status_observed={_display_value(data, FIELD_ALIASES['status'])}")
    print(f"market_observed={_display_value(data, FIELD_ALIASES['market'])}")
    realtime = _first_value(data, FIELD_ALIASES["is_realtime"])
    print(f"realtime_type={type(realtime).__name__ if realtime is not None else 'missing'}")
    print(f"missing_aliases={','.join(missing) or 'none'}")
    print(f"unused_aliases={','.join(unused) or 'none'}")
    print(f"unknown_fields={','.join(unknown) or 'none'}")


def _public_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    result = {}
    for key in _WRAPPER_KEYS:
        try:
            item = getattr(value, key)
        except Exception:
            continue
        result[key] = item
    if result:
        return result
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        return {
            str(key): item
            for key, item in attributes.items()
            if isinstance(key, str) and not key.startswith("_")
        }
    return {}


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            key = str(key)
            if not _safe_key(key):
                continue
            result[key] = _sanitize(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    public = _public_mapping(value)
    return _sanitize(public) if public else None


def _safe_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.casefold().replace("-", "_")
    if normalized in _SENSITIVE_EXACT_KEYS:
        return False
    return not any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _safe_keys(value: Mapping[str, Any]) -> list[str]:
    return sorted(str(key) for key in value if _safe_key(key))


def _first_value(data: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in data:
            return data[alias]
    return None


def _display_value(data: Mapping[str, Any], aliases: tuple[str, ...]) -> str:
    value = _first_value(data, aliases)
    if value is None:
        return "missing"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)):
        return str(value)[:128]
    if isinstance(value, datetime):
        return value.isoformat()
    return f"<{type(value).__name__}>"


def _timestamp_format(value: Any) -> str:
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, bool):
        return "invalid_bool"
    if isinstance(value, (int, float)):
        return "unix_milliseconds" if value > 1_000_000_000_000 else "unix_seconds"
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
            return "iso8601"
        except ValueError:
            return "string_unknown"
    return "missing" if value is None else f"unsupported_{type(value).__name__}"


def _timestamp_timezone(value: Any) -> str:
    if isinstance(value, datetime):
        return str(value.tzinfo) if value.tzinfo is not None else "naive"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "utc_by_contract"
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
            return str(parsed.tzinfo) if parsed.tzinfo is not None else "naive"
        except ValueError:
            return "unknown"
    return "missing"


if __name__ == "__main__":
    raise SystemExit(main())
