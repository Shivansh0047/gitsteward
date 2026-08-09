from fastapi import APIRouter, HTTPException

from graph.runtime import get_run_state, get_run_timeline

router = APIRouter()


@router.get("/runs/{run_id}/state")
async def run_state(run_id: str, repo: str = "Shivansh0047/RAG-Chatbot-Service"):
    state = get_run_state(repo, run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No run found with this ID")
    return state


@router.get("/runs/{run_id}/timeline")
async def run_timeline(run_id: str, repo: str = "Shivansh0047/RAG-Chatbot-Service"):
    timeline = get_run_timeline(repo, run_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="No run found with this ID")
    return {"run_id": run_id, "timeline": timeline}