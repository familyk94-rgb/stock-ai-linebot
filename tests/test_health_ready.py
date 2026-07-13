import asyncio
from pathlib import Path

from fastapi import Response

from app import main


def run(coro):
    return asyncio.run(coro)


def test_health_is_fixed_and_does_not_call_external_services(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP called")))
    assert run(main.health()) == {"status": "ok", "service": "stock-ai-linebot"}


def _configure_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "LINE_CHANNEL_SECRET", "line-secret")
    monkeypatch.setattr(main.config, "LINE_CHANNEL_ACCESS_TOKEN", "line-token")
    monkeypatch.setattr(main.config, "FINMIND_API_TOKEN", "finmind-token")
    monkeypatch.setattr(main.config, "OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(main, "DEFAULT_CACHE_PATH", tmp_path / "asset.json")
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)


def test_ready_with_complete_local_configuration(monkeypatch, tmp_path):
    _configure_ready(monkeypatch, tmp_path)
    response = Response()
    result = run(main.ready(response))
    assert response.status_code == 200
    assert result["status"] == "ready"
    assert result["checks"] == {
        "line": "ok", "finmind": "ok", "openai": "ok", "asset_cache": "ok",
        "modules": "ok",
    }
    assert "line-secret" not in str(result)
    assert "line-token" not in str(result)
    assert "finmind-token" not in str(result)


def test_ready_missing_line_is_503(monkeypatch, tmp_path):
    _configure_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(main.config, "LINE_CHANNEL_SECRET", None)
    response = Response()
    result = run(main.ready(response))
    assert response.status_code == 503
    assert result["checks"]["line"] == "missing"


def test_ready_missing_finmind_is_503(monkeypatch, tmp_path):
    _configure_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(main.config, "FINMIND_API_TOKEN", None)
    response = Response()
    result = run(main.ready(response))
    assert response.status_code == 503
    assert result["checks"]["finmind"] == "missing"


def test_missing_openai_is_degraded_but_ready(monkeypatch, tmp_path):
    _configure_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(main.config, "OPENAI_API_KEY", None)
    response = Response()
    result = run(main.ready(response))
    assert response.status_code == 200
    assert result["checks"]["openai"] == "degraded"


def test_unreadable_asset_cache_directory_is_not_ready(monkeypatch, tmp_path):
    _configure_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "DEFAULT_CACHE_PATH", Path(tmp_path / "missing" / "asset.json"))
    response = Response()
    result = run(main.ready(response))
    assert response.status_code == 503
    assert result["checks"]["asset_cache"] == "unavailable"


def test_required_module_import_failure_is_not_ready(monkeypatch, tmp_path):
    _configure_ready(monkeypatch, tmp_path)
    real_import = main.import_module

    def failing_import(name):
        if name == "services.ai_service":
            raise ImportError("private details")
        return real_import(name)

    monkeypatch.setattr(main, "import_module", failing_import)
    response = Response()
    result = run(main.ready(response))
    assert response.status_code == 503
    assert result["checks"]["modules"] == "error"
    assert "private details" not in str(result)


def test_cache_directory_must_be_writable(monkeypatch, tmp_path):
    _configure_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(main.tempfile, "NamedTemporaryFile", lambda **kwargs: (_ for _ in ()).throw(PermissionError()))
    response = Response()
    result = run(main.ready(response))
    assert response.status_code == 503
    assert result["checks"]["asset_cache"] == "unavailable"
