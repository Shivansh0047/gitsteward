import bootstrap # force the correct order of imporitng which could break the code

from fastapi import FastAPI
import logging
from contextlib import asynccontextmanager
from webhooks import router as webhooks_router
from rag.embeddings import build_vectorstore

logging.basicConfig(level=logging.INFO) # This turns logging output on so we can actually see it in the terminal.
logger = logging.getLogger("gitsteward.startup")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Building README vectorstore...")
    build_vectorstore()
    logger.info("Vectorstore ready.")
    yield  # server runs here, handling requests, everything before yield runs once at startup
    # (anything after yield would run on shutdown — nothing needed here yet)

app = FastAPI(title="GitSteward", lifespan=lifespan)
app.include_router(webhooks_router) # merges the routes we defined in webhooks.py into our main app

@app.get("/health")
async def health():
    return {"status": "ok"}