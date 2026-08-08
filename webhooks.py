import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from config import settings

from github_app import get_commit_diffs
from graph.runtime import start_run, resume_run  # replaces the manual analyze/commit/PR pipeline
from graph.pr_tracking import get_runs_for_pr  # looks up which run(s) a closed PR belongs to

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
    # never treat our own output folder as something needing analysis —
    # prevents merges of our own PRs from re-triggering the whole pipeline
    return sorted(f for f in changed if not f.startswith("gitsteward-docs/"))

# This function gets changed files, run through the real LLM pipeline now (was match_anchors())
def _handle_push(payload: dict) -> None:

    ref = payload.get("ref", "") # guard against self loop
    if ref != "refs/heads/main":
        logger.info("Push to '%s', not main — ignoring (likely our own review branch).", ref)
        return

    sha = payload.get("after")
    repo = payload.get("repository", {}).get("full_name")
    changed_files = _get_changed_files(payload)
    logger.info("Push %s touched %d file(s): %s", sha, len(changed_files), changed_files) # debug check

    if not changed_files:
        logger.info("No changed files — nothing to do.")  # early exit, no diffs to fetch as github send empty patch file
        return

    diffs = get_commit_diffs(sha)  # {file_path: unified_diff_patch}, real diff text for the LLM
    if not diffs:
        logger.info("No usable diffs for this push (binary/huge files only?) — nothing to do.")
        return

    # everything which used to be manual (analyze -> branch -> commit -> PR),
    # now the graph's nodes do all of that internally — this one call replaces it all
    result = start_run(repo, sha, changed_files, diffs)
    logger.info("Run %s reached status=%s", sha, result.get("status"))

# handles the review decision, was previously received and ignored entirely
def _handle_pull_request(payload: dict) -> None:
    action = payload.get("action")
    if action != "closed":
        logger.info("Ignoring pull_request action '%s' (only 'closed' triggers a resume).", action)
        return

    pr = payload.get("pull_request", {})
    pr_number = pr.get("number")
    merged = pr.get("merged", False)
    repo = payload.get("repository", {}).get("full_name")

    run_ids = get_runs_for_pr(repo, pr_number)  # which paused run(s) does this PR belong to
    if not run_ids:
        logger.info("No tracked runs waiting on PR #%s — nothing to resume.", pr_number)
        return

    for run_id in run_ids:
        logger.info("Resuming run %s for PR #%s (merged=%s)", run_id, pr_number, merged)
        resume_run(repo, run_id, merged=merged)

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
        _handle_push(payload) # Handle push
    elif x_github_event == "pull_request":
        _handle_pull_request(payload)  # now we also look for pull request was previously ignored

    return {"status": "received", "event": x_github_event}