import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from config import settings

from github_app import (
    commit_multiple_files,     # replaces write_repo_file for batched writes
    build_tracking_index_content,  # replaces update_tracking_index
    get_commit_diffs,
    get_or_create_review_branch,
    open_review_pr,
    post_commit_comment,
)
from rag.llm import analyze_push_diffs, rewrite_merged_section  # real LLM reasoning, replaces hardcoded doc_rules
from rag.readme_source import build_full_readme_preview  # new

# A named logger for this file specifically — lets us filter/identify
# log lines as coming from "testforge.webhooks" rather than just "root"
logger = logging.getLogger("gitsteward.webhooks")
router = APIRouter() # A separate router object


def _verify_signature(raw_body: bytes, signature_header: str | None) -> None:
    # Reject immediately if GitHub didn't sign the request at all
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256")

    # Recompute the signature ourselves using our shared secret
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()

    # Timing-safe comparison
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

# A temp function to get chainged files, payload included list of commits, each with added/modified/removed
def _get_changed_files(payload: dict) -> list[str]:
    changed: set[str] = set()
    for commit in payload.get("commits", []):
        changed.update(commit.get("added", []))
        changed.update(commit.get("modified", []))
        changed.update(commit.get("removed", []))
    return sorted(changed)

# This function gets changed files, run through the real LLM pipeline now (was match_anchors())
def _handle_push(payload: dict) -> None:

    ref = payload.get("ref", "") # guard against self loop
    if ref != "refs/heads/main":
        logger.info("Push to '%s', not main — ignoring (likely our own review branch).", ref)
        return

    sha = payload.get("after")
    changed_files = _get_changed_files(payload)
    logger.info("Push %s touched %d file(s): %s", sha, len(changed_files), changed_files) # debug check

    if not changed_files:
        logger.info("No changed files — nothing to do.")  # early exit, no diffs to fetch as github send empty patch file
        return

    diffs = get_commit_diffs(sha)  # new — {file_path: unified_diff_patch}, real diff text for the LLM
    if not diffs:
        logger.info("No usable diffs for this push (binary/huge files only?) — nothing to do.")  # new
        return

    merged = analyze_push_diffs(diffs)  # replaces match_anchors(); {anchor: {heading, original_content, reasons, diffs}}
    if not merged:
        logger.info("LLM found no stale sections for this push — nothing to do.")  # new — same guard, new source
        return

    branch, is_new = get_or_create_review_branch()
    logger.info("Using review branch '%s' (new=%s)", branch, is_new)

    anchor_updates: dict[str, str] = {}     # replaces the old all_anchors set
    anchor_summaries: dict[str, str] = {}   # feeds the tracking index's Summary field
    rewritten_by_anchor: dict[str, str] = {}
    files_to_commit: dict[str, str] = {}  # everything we're about to write, batched into ONE commit

    # For every stale anchor the LLM found, write the REAL rewritten markdown (was placeholder text) to gitsteward-docs/<anchor>.md on that branch and batch all together
    for anchor, section in merged.items():
        rewritten = rewrite_merged_section(section) # actual LLM-drafted section text
        summary = " / ".join(section["reasons"])  # combined reasons across all contributing files

        content = (
            "---\n"
            f"source_anchor: \"README.md#{anchor}\"\n"
            f"source_commit: \"{sha}\"\n"
            "status: \"updated\"\n"
            "---\n\n"
            f"**Why flagged:** {summary}\n\n" # short explanation line
            f"{rewritten}\n" # real content
        )
        files_to_commit[f"gitsteward-docs/{anchor}.md"] = content

        anchor_updates[anchor] = "updated"
        anchor_summaries[anchor] = summary
        rewritten_by_anchor[anchor] = rewritten

    files_to_commit["gitsteward-docs/modified_gitsteward_readme.md"] = build_full_readme_preview(rewritten_by_anchor)
    files_to_commit["gitsteward-docs/README.md"] = build_tracking_index_content(anchor_updates, sha, branch, summaries=anchor_summaries)

    # ONE commit, containing every file above — must happen BEFORE opening the PR,
    # since a brand-new branch has zero diff from main until this runs
    commit_multiple_files(branch, files_to_commit, message=f"GitSteward: update {len(merged)} section(s) (push {sha[:7]})")

    if is_new:
        pr_number = open_review_pr(
            branch,
            title="GitSteward: doc suggestions",
            body="Automated suggestions for potentially stale README sections. Review each file under `gitsteward-docs/` and merge or close.",
        )
        logger.info("Opened new PR #%s", pr_number)
        comment = f"GitSteward opened PR #{pr_number} for review — {len(merged)} section(s) flagged."  # len(merged) not len(all_anchors)
    else:
        logger.info("Updated existing open PR's branch.")
        comment = f"GitSteward updated its open review PR — {len(merged)} section(s) flagged."

    post_commit_comment(sha, comment)

@router.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=None), #  "push", "pull_request"
    x_hub_signature_256: str = Header(default=None), # the signature
):
    raw_body = await request.body()          # raw bytes, needed for signature check
    _verify_signature(raw_body, x_hub_signature_256)

    payload = await request.json()           # safe to parse now that it's verified

    logger.info(
        "Received verified GitHub event: %s (repo=%s)", # For now, just log
        x_github_event,
        payload.get("repository", {}).get("full_name"),
    )

    if x_github_event == "push":
        _handle_push(payload) # For now we just handle push

    return {"status": "received", "event": x_github_event}