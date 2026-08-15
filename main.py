import bootstrap # force the correct order of imporitng which could break the code

from fastapi import FastAPI
import logging
from contextlib import asynccontextmanager
from webhooks import router as webhooks_router
from graph.runtime import _get_compiled_graph
from graph.pr_tracking import ensure_table as ensure_pr_table  # renamed on import — two "ensure_table" functions now exist
from graph.repo_registry import ensure_table as ensure_repos_table  # new — the repos table

from observability import router as observability_router

logging.basicConfig(level=logging.INFO) # This turns logging output on so we can actually see it in the terminal.
logger = logging.getLogger("gitsteward.startup")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # no more build_vectorstore() call here — vectorstores are now pgvector-backed,
    # per repo, and built lazily on first use rather than once at startup for one hardcoded repo
    _get_compiled_graph()   # forces checkpointer.setup() to run now, not on first webhook
    ensure_pr_table()
    ensure_repos_table()  # new
    logger.info("Graph compiled, tables ready. Vectorstores are pgvector-backed and build lazily per repo.")
    yield  # server runs here, handling requests, everything before yield runs once at startup
    # (anything after yield would run on shutdown — nothing needed here yet)

app = FastAPI(title="GitSteward", lifespan=lifespan)
app.include_router(webhooks_router) # merges the routes we defined in webhooks.py into our main app
app.include_router(observability_router) # include the observability router

@app.get("/health")
async def health():
    return {"status": "ok"}