import bootstrap

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from config import settings
from graph.build import build_graph

_checkpointer_cm = None   # the context manager itself, kept open for the app's lifetime
_compiled_graph = None

def _get_compiled_graph():
    """Builds the checkpointer + compiles the graph once, reused after that"""
    global _checkpointer_cm, _compiled_graph # Increased Scope wo we can reuse it
    if _compiled_graph is None:
        _checkpointer_cm = PostgresSaver.from_conn_string(settings.database_url) # Returns a context manager
        checkpointer = _checkpointer_cm.__enter__()  # manually enter, since we're keeping it open long-term
        checkpointer.setup()  # one-time table creation, running it again when the tables already exist just does nothing.
        _compiled_graph = build_graph().compile(checkpointer=checkpointer)
    return _compiled_graph

def _make_thread_id(repo: str, run_id: str) -> str:
    return f"{repo}:{run_id}"  # repo-aware, to support multi-repo later

def start_run(repo: str, run_id: str, changed_files: list[str], diffs: dict[str, str]) -> dict:
    """Invoke the graph for a brand new run brand-new run for one push."""
    graph = _get_compiled_graph()
    config = {"configurable": {"thread_id": _make_thread_id(repo, run_id)}}

    initial_state = {
        "run_id": run_id,
        "repo": repo,
        "changed_files": changed_files,
        "diffs": diffs,
        "section_results": {},
        "branch": None,
        "pr_number": None,
        "status": "running",
    }
    return graph.invoke(initial_state, config)

def resume_run(repo: str, run_id: str, merged: bool) -> dict:
    """Resumes a run that's currently paused at await_review_node."""
    graph = _get_compiled_graph()
    config = {"configurable": {"thread_id": _make_thread_id(repo, run_id)}} # Get prev thread_id, safe as it is deterministic
    return graph.invoke(Command(resume=merged), config)