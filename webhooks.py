import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from config import settings

from doc_rules import match_anchors
from github_app import (
    get_or_create_review_branch,
    open_review_pr,
    post_commit_comment,
    write_repo_file,
)

# A named logger for this file specifically — lets us filter/identify
# log lines as coming from "testforge.webhooks" rather than just "root"
logger = logging.getLogger("testforge.webhooks")
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

# This function gets changed files, run through match_anchors()
def _handle_push(payload: dict) -> None:
    sha = payload.get("after")
    changed_files = _get_changed_files(payload)
    logger.info("Push %s touched %d file(s): %s", sha, len(changed_files), changed_files) # debug check

    file_to_anchors = match_anchors(changed_files)

    if not file_to_anchors:
        logger.info("No matched README sections for this push — nothing to do.")
        return

    # Collect every unique anchor across all matched files
    all_anchors: set[str] = set()
    for anchors in file_to_anchors.values():
        all_anchors.update(anchors)

    branch, is_new = get_or_create_review_branch()
    logger.info("Using review branch '%s' (new=%s)", branch, is_new)
    # For every unique anchor, builds the placeholder markdown (with front-matter: which section, which commit triggered it, status) and writes it to test-forge-docs/<anchor>.md on that branch.
    for anchor in sorted(all_anchors):
        content = (
            "---\n"
            f"source_anchor: \"README.md#{anchor}\"\n"
            f"source_commit: \"{sha}\"\n"
            "status: \"skipped\"\n"
            "---\n\n"
            f"This commit touched files that may affect the `#{anchor}` section. "
            "No AI reasoning yet — Phase 1 pattern-matching only.\n"
        )
        write_repo_file(
            path=f"test-forge-docs/{anchor}.md",
            content=content,
            message=f"TestForge: flag #{anchor} (push {sha[:7]})",
            branch=branch,
        )

    if is_new:
        pr_number = open_review_pr(
            branch,
            title="TestForge: doc suggestions",
            body="Automated suggestions for potentially stale README sections. Review each file under `test-forge-docs/` and merge or close.",
        )
        logger.info("Opened new PR #%s", pr_number)
        comment = f"TestForge opened PR #{pr_number} for review — {len(all_anchors)} section(s) flagged."
    else:
        logger.info("Updated existing open PR's branch.")
        comment = f"TestForge updated its open review PR — {len(all_anchors)} section(s) flagged."

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