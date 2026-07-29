from fastapi import FastAPI

app = FastAPI(title="TestForge")


@app.get("/health")
async def health():
    return {"status": "ok"}