from fastapi import FastAPI

app = FastAPI(
    title="股市柑仔店 AI 投資助理",
    version="1.0.0"
)

@app.get("/")
async def home():
    return {
        "project": "股市柑仔店 AI 投資助理",
        "status": "Running",
        "version": "1.0.0"
    }