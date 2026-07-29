import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from config import settings

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

    return {"status": "received", "event": x_github_event}