import os
import tempfile
from importlib import import_module
from pathlib import Path

from fastapi import FastAPI, Response

from app import config
from app.webhook import router as webhook_router
from services.asset_service import DEFAULT_CACHE_PATH

REQUIRED_MODULES = (
    "app.webhook",
    "services.market_service",
    "services.ai_service",
    "app.flex.builder",
)


def _required_modules_available() -> bool:
    try:
        for module_name in REQUIRED_MODULES:
            import_module(module_name)
        return True
    except Exception:
        return False


def _asset_cache_directory_available(cache_path: Path) -> bool:
    directory = cache_path.parent
    if not directory.is_dir() or not os.access(directory, os.R_OK | os.W_OK):
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".ready-", delete=True):
            pass
        return True
    except (OSError, PermissionError):
        return False

app = FastAPI(
    title="股市柑仔店 AI 投資助理",
    version="1.0.0"
)

app.include_router(webhook_router)

@app.get("/")
async def home():
    return {
        "project": "股市柑仔店 AI 投資助理",
        "status": "Running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stock-ai-linebot"}


@app.get("/ready")
async def ready(response: Response):
    line_ok = bool(config.LINE_CHANNEL_SECRET and config.LINE_CHANNEL_ACCESS_TOKEN)
    finmind_ok = bool(os.getenv("FINMIND_TOKEN") or config.FINMIND_API_TOKEN)
    openai_ok = bool(config.OPENAI_API_KEY)
    cache_path = Path(DEFAULT_CACHE_PATH)
    cache_ok = _asset_cache_directory_available(cache_path)
    modules_ok = _required_modules_available()
    checks = {
        "line": "ok" if line_ok else "missing",
        "finmind": "ok" if finmind_ok else "missing",
        "openai": "ok" if openai_ok else "degraded",
        "asset_cache": "ok" if cache_ok else "unavailable",
        "modules": "ok" if modules_ok else "error",
    }
    is_ready = line_ok and finmind_ok and cache_ok and modules_ok
    response.status_code = 200 if is_ready else 503
    return {"status": "ready" if is_ready else "not_ready", "checks": checks}
