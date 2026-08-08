from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from graph.pr_tracking import record_pr_run

from graph.state import WorkflowState
from rag.llm import analyze_push_diffs, rewrite_merged_section
from rag.readme_source import build_full_readme_preview
from github_app import (
    get_or_create_review_branch,
    commit_multiple_files,
    open_review_pr,
    post_commit_comment,
    build_tracking_index_content,
)

def resolve_branch_node(state: WorkflowState) -> dict:
    """Runs FIRST, before any LLM reasoning — so analyze_node knows which
    branch (if any) to check for already-proposed content."""
    branch, is_new, existing_pr_number = get_or_create_review_branch()
    return {
        "branch": branch,
        "is_new_branch": is_new,
        "pr_number": None if is_new else existing_pr_number,
    }

def analyze_node(state: WorkflowState) -> dict:
    """Run the LLM reasoning, same logic as before — just now it
    READS from state (state['diffs']) instead of a function parameter,
    and RETURNS a dict of updates instead of directly writing files."""
    merged = analyze_push_diffs(state["diffs"], branch=state.get("branch"))  # branch now available

    section_results = {}
    for anchor, section in merged.items():
        rewritten = rewrite_merged_section(section)
        section_results[anchor] = {
            "anchor": anchor,
            "status": "updated",
            "reasons": section["reasons"],
            "content": rewritten,
        }

    return {"section_results": section_results}  # LangGraph merges this into the real state automatically


def commit_and_open_pr_node(state: WorkflowState) -> dict:
    """Everything that writes to GitHub — branch, commit, PR."""
    if not state["section_results"]:
        return {"status": "done"}  # nothing to propose, skip straight to done

    branch = state["branch"]          # already resolved, no need to call get_or_create_review_branch again
    is_new = state["is_new_branch"]

    files_to_commit = {}
    rewritten_by_anchor = {}
    for anchor, result in state["section_results"].items():
        files_to_commit[f"gitsteward-docs/{anchor}.md"] = (
            "---\n"
            f"source_anchor: \"README.md#{anchor}\"\n"
            f"source_commit: \"{state['run_id']}\"\n"
            f"status: \"{result['status']}\"\n"
            "---\n\n"
            f"**Why flagged:** {' / '.join(result['reasons'])}\n\n"
            f"{result['content']}\n"
        )
        rewritten_by_anchor[anchor] = result["content"]

    files_to_commit["gitsteward-docs/modified_gitsteward_readme.md"] = build_full_readme_preview(rewritten_by_anchor)

    anchor_updates = {a: r["status"] for a, r in state["section_results"].items()}
    anchor_summaries = {a: " / ".join(r["reasons"]) for a, r in state["section_results"].items()}
    files_to_commit["gitsteward-docs/README.md"] = build_tracking_index_content(
        anchor_updates, state["run_id"], branch, summaries=anchor_summaries
    )

    commit_multiple_files(branch, files_to_commit, message=f"GitSteward: update {len(state['section_results'])} section(s) (push {state['run_id'][:7]})")

    if is_new:
        pr_number = open_review_pr(
            branch,
            title="GitSteward: doc suggestions",
            body="Automated suggestions for potentially stale README sections. Review each file under `gitsteward-docs/` and merge or close.",
        )
        comment = f"GitSteward opened PR #{pr_number} for review — {len(state['section_results'])} section(s) flagged."
    else:
        pr_number = state["pr_number"]  # already fetched in resolve_branch_node
        comment = f"GitSteward updated its open review PR — {len(state['section_results'])} section(s) flagged."

    record_pr_run(state["repo"], pr_number, state["run_id"])   # link this run to its PR
    post_commit_comment(state["run_id"], comment)

    return {"branch": branch, "pr_number": pr_number, "status": "waiting_approval"}


def await_review_node(state: WorkflowState) -> dict:
    """Pause point. interrupt() halts the graph here —
    LangGraph saves the current state to Postgres and returns control to
    whoever called the graph (our webhook handler), without running any
    more nodes. Days later, a separate call to resume the graph with a
    value (merged: True/False) picks up exactly here, as if this function
    had simply returned that value all along."""
    if state["status"] != "waiting_approval":
        return {}  # nothing was proposed, nothing to wait on — skip through

    merged = interrupt({"pr_number": state["pr_number"], "run_id": state["run_id"]}) # Pause the grapg and save to SQL
    return {"merged_result": merged}


def finalize_node(state: WorkflowState) -> dict:
    """Runs only after resume — marks the run done, and updates
    each section's final status based on whether the human merged or closed."""
    if state["status"] == "done":
        return {}  # already finished (e.g. nothing was stale) — nothing to finalize
    merged = state.get("merged_result", False)
    final_status = "updated" if merged else "skipped"

    updated_results = {}
    for anchor, result in state["section_results"].items():
        updated_results[anchor] = {**result, "status": final_status}

    return {"section_results": updated_results, "status": "done"}


def build_graph():
    builder = StateGraph(WorkflowState)
    builder.add_node("resolve_branch", resolve_branch_node)   # runs first now
    builder.add_node("analyze", analyze_node)
    builder.add_node("commit_and_pr", commit_and_open_pr_node)
    builder.add_node("await_review", await_review_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "resolve_branch")
    builder.add_edge("resolve_branch", "analyze")
    builder.add_edge("analyze", "commit_and_pr")
    builder.add_edge("commit_and_pr", "await_review")
    builder.add_edge("await_review", "finalize")
    builder.add_edge("finalize", END)

    return builder # Not Compiled as it need checkpointer