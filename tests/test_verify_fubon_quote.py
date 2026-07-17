import json

from tools.verify_fubon_quote import (
    _extract_quote_payload,
    _missing_configuration,
    _print_report,
    _write_fixture,
)


BASE_ENV = {
    "FUBON_NEO_ENABLED": "true",
    "FUBON_USER_ID": "configured",
    "FUBON_PASSWORD": "configured",
    "FUBON_CERT_PATH": "configured",
    "FUBON_CERT_PASSWORD": "configured",
}


def test_missing_certificate_password_is_missing_configuration(capsys):
    environ = {
        key: value for key, value in BASE_ENV.items() if key != "FUBON_CERT_PASSWORD"
    }
    assert _missing_configuration(environ) is True
    assert capsys.readouterr().out == ""


def test_empty_certificate_password_passes_configuration_check(capsys):
    assert _missing_configuration({**BASE_ENV, "FUBON_CERT_PASSWORD": ""}) is False
    assert capsys.readouterr().out == ""


def test_empty_user_id_is_missing_configuration(capsys):
    assert _missing_configuration({**BASE_ENV, "FUBON_USER_ID": ""}) is True
    assert capsys.readouterr().out == ""


def test_wrapper_response_extracts_data():
    payload = {"symbol": "2330", "lastPrice": 100}
    wrapper, data, schema = _extract_quote_payload(
        {"success": True, "error": None, "data": payload}
    )
    assert schema == "wrapper"
    assert wrapper["success"] is True
    assert data == payload


def test_flat_response_is_quote_payload():
    payload = {"symbol": "2330", "lastPrice": 100, "lastUpdated": 1700000000000}
    wrapper, data, schema = _extract_quote_payload(payload)
    assert schema == "flat"
    assert wrapper == {}
    assert data == payload


def test_flat_response_without_symbol_is_rejected():
    assert _extract_quote_payload({"lastPrice": 100}) == (
        {"lastPrice": 100},
        {},
        "invalid",
    )


def test_arbitrary_error_dict_is_not_quote_payload():
    response = {"error": "request failed", "message": "not a quote"}
    assert _extract_quote_payload(response) == (response, {}, "invalid")


def test_flat_payload_writes_sanitized_fixture(tmp_path):
    payload = {
        "symbol": "2330",
        "lastPrice": 100,
        "referencePrice": 99,
        "openPrice": 98,
        "total": 12345,
        "lastUpdated": 1700000000000,
        "Token": "TOKEN-CREDENTIAL",
        "account": "ACCOUNT-CREDENTIAL",
        "unrelated": "not-required",
    }
    output = tmp_path / "production_quote_sample.json"
    _write_fixture(output, {}, payload, "flat")
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved == {
        "symbol": "2330",
        "lastPrice": 100,
        "referencePrice": 99,
        "openPrice": 98,
        "total": 12345,
        "lastUpdated": 1700000000000,
    }
    assert "CREDENTIAL" not in output.read_text(encoding="utf-8")


def test_report_does_not_output_credentials(capsys):
    payload = {
        "symbol": "2330",
        "lastPrice": 100,
        "Token": "TOKEN-CREDENTIAL",
        "account": "ACCOUNT-CREDENTIAL",
    }
    _print_report(payload, {}, payload)
    output = capsys.readouterr().out
    assert "CREDENTIAL" not in output
    assert "Token" not in output
    assert "account" not in output
