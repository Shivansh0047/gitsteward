from fastapi import FastAPI
import logging
from webhooks import router as webhooks_router

logging.basicConfig(level=logging.INFO) # This turns logging output on so we can actually see it in the terminal.

app = FastAPI(title="GitSteward")
app.include_router(webhooks_router) # merges the routes we defined in webhooks.py into our main app


@app.get("/health")
async def health():
    return {"status": "ok"}