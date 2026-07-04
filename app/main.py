from fastapi import FastAPI
from app.webhook import router as webhook_router

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