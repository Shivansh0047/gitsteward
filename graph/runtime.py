import bootstrap

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from config import settings
from graph.build import build_graph

_checkpointer_cm = None   # the context manager itself, kept open for the app's lifetime
_compiled_graph = None

def _get_compiled_graph():
    """Builds the checkpointer + compiles the graph once, reused after that"""
    global _checkpointer_cm, _compiled_graph, _checkpointer # Increased Scope wo we can reuse it
    if _compiled_graph is None:
        _checkpointer_cm = PostgresSaver.from_conn_string(settings.database_url) # Returns a context manager
        checkpointer = _checkpointer_cm.__enter__()  # manually enter, since we're keeping it open long-term
        checkpointer.setup()  # one-time table creation, running it again when the tables already exist just does nothing.
        _compiled_graph = build_graph().compile(checkpointer=checkpointer)
    return _compiled_graph

def _make_thread_id(repo: str, run_id: str) -> str:
    return f"{repo}:{run_id}"  # repo-aware, to support multi-repo later

def _reconnect_if_needed() -> None:
    """Neon free tier auto-suspends after 5 min inactivity and kills open
    connections. Recompile the graph with a fresh connection if the old
    one is dead."""
    global _checkpointer_cm, _compiled_graph, _checkpointer
    try:
        # lightweight ping to check if the connection is still alive
        with _checkpointer.conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        # connection is dead — reopen everything
        try:
            _checkpointer_cm.__exit__(None, None, None)
        except Exception:
            pass
        _compiled_graph = None
        _checkpointer_cm = None
        _checkpointer = None
        _get_compiled_graph()  # rebuilds fresh

def start_run(repo: str, installation_id: int, run_id: str, changed_files: list[str], diffs: dict[str, str]) -> dict:
    """Invoke the graph for a brand new run brand-new run for one push."""
    _reconnect_if_needed()  # check before every real use
    graph = _get_compiled_graph()
    config = {"configurable": {"thread_id": _make_thread_id(repo, run_id)}}

    initial_state = {
        "run_id": run_id,
        "repo": repo,
        "installation_id": installation_id,  # new — carried in state so a resume doesn't need the original webhook payload
        "changed_files": changed_files,
        "diffs": diffs,
        "section_results": {},
        "branch": None,
        "pr_number": None,
        "status": "running",
    }
    return graph.invoke(initial_state, config)

def resume_run(repo: str, run_id: str, merged: bool) -> dict:
    _reconnect_if_needed()
    """Resumes a run that's currently paused at await_review_node.
    No installation_id needed here — it's already sitting in the
    checkpointed state from start_run(), restored automatically."""
    graph = _get_compiled_graph()
    config = {"configurable": {"thread_id": _make_thread_id(repo, run_id)}} # Get prev thread_id, safe as it is deterministic
    return graph.invoke(Command(resume=merged), config)

def get_run_state(repo: str, run_id: str) -> dict | None:
    """Fetches the current state of a run directly from the checkpointer,
    without needing to resume it — just a read, not an action."""
    _reconnect_if_needed()
    graph = _get_compiled_graph()
    config = {"configurable": {"thread_id": _make_thread_id(repo, run_id)}}
    snapshot = graph.get_state(config)
    if not snapshot.values:
        return None  # no checkpoint exists for this thread at all
    return snapshot.values


def get_run_timeline(repo: str, run_id: str) -> list[dict]:
    """Full history of every checkpoint saved for this run — each step
    the graph passed through, in order."""
    _reconnect_if_needed()
    graph = _get_compiled_graph()
    config = {"configurable": {"thread_id": _make_thread_id(repo, run_id)}}
    history = list(graph.get_state_history(config))
    return [
        {
            "step": h.metadata.get("step"),
            "status": h.values.get("status"),
            "next_node": h.next,
        }
        for h in reversed(history)  # oldest first, reads like a timeline
    ]