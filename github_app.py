from github import Github, GithubIntegration

from config import settings

from datetime import datetime, timezone


def _load_private_key() -> str: # read .pem file
    with open(settings.github_app_private_key_path, "r") as f:
        return f.read()


def get_installation_client() -> Github:
    integration = GithubIntegration(settings.github_app_id, _load_private_key()) # Object of GitSteward, the App, signs jwt token
    access_token = integration.get_access_token(settings.github_installation_id) # Exchnage KWT for real token
    return Github(access_token.token) # A normal PyGithub client already authicanted


def get_repo():
    client = get_installation_client()
    return client.get_repo(f"{settings.demo_repo_owner}/{settings.demo_repo_name}")


REVIEW_BRANCH = "gitsteward/doc-suggestions"

# Create new revier branch or get the old one
def get_or_create_review_branch(base: str = "main") -> tuple[str, bool]:
    repo = get_repo()

    open_prs = repo.get_pulls(state="open", head=f"{repo.owner.login}:{REVIEW_BRANCH}") # Check if there is some brnch which alread exicts
    for pr in open_prs:
        return REVIEW_BRANCH, False  # reuse — already open, just add to it

    base_sha = repo.get_branch(base).commit.sha  # where main currently points
    repo.create_git_ref(ref=f"refs/heads/{REVIEW_BRANCH}", sha=base_sha)  # Name the branch after pointer of commit of main
    return REVIEW_BRANCH, True

def get_commit_diffs(sha: str) -> dict[str, str]: # Get actual code difference, so LLM can reason Properly
    """Returns {file_path: unified_diff_patch} for every file changed in this commit."""
    repo = get_repo()
    commit = repo.get_commit(sha)
    return {f.filename: f.patch for f in commit.files if f.patch}  # f.patch is None for binary/huge files

# Writing files onto that branch
def write_repo_file(path: str, content: str, message: str, branch: str) -> None:
    repo = get_repo()
    try:
        existing = repo.get_contents(path, ref=branch) # Get file
        repo.update_file(path, message, content, existing.sha, branch=branch) # Update the file
    except Exception:
        repo.create_file(path, message, content, branch=branch) # Create new file if it doesnt exist

# Opening a pull request
def open_review_pr(branch: str, title: str, body: str, base: str = "main") -> int:
    repo = get_repo()
    pr = repo.create_pull(title=title, body=body, head=branch, base=base)
    return pr.number # return PR number

# A helper functin to mention this is a GitSteward commit
def post_commit_comment(sha: str, body: str) -> None:
    repo = get_repo()
    commit = repo.get_commit(sha)
    commit.create_comment(body)

TRACKING_INDEX_PATH = "gitsteward-docs/README.md" # To keep a doc of what changed, as a separate history, also can be use as memory for LLM, after cold start of Render

# turns the existing markdown index file's text into a Python dict, so we can update it programmatically.
def _parse_tracking_rows(content: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    blocks = content.split("\n## ")[1:]  # each block = one anchor's section, skip intro text before first "##"

    for block in blocks:
        lines = block.strip().splitlines()
        heading = lines[0]  # e.g. "Stack (#stack)"
        section, anchor = heading.rsplit(" (#", 1)  # split from the right, only on the last " (#"
        anchor = anchor.rstrip(")")  # drop the trailing ")"

        entry = {"section": section}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)  # split only on the first ":"
                entry[key.strip().lower()] = value.strip()

        rows[anchor] = entry

    return rows

# the reverse: turns that dict back into the markdown text we'll write to the file
def _render_tracking_index(rows: dict[str, dict[str, str]]) -> str:
    lines = [
        "# GitSteward — Doc Suggestions Index",
        "",
        "Auto-generated summary of every README section GitSteward has flagged.",
        "",
    ]
    for anchor in sorted(rows):  # sorted = stable, predictable order across runs
        r = rows[anchor]
        lines += [
            f"## {r['section']} (#{anchor})",
            f"Status: {r['status']}",
            f"Commit: {r['commit'][:7]}",  # short SHA, matches GitHub's own convention
            f"Updated: {r['updated']}",
            "",  # blank line between blocks
        ]
    return "\n".join(lines) + "\n"

# fetches the current file (if any), merges in this run's new anchor statuses, and writes the updated file back to the branch.
def update_tracking_index(anchor_updates: dict[str, str], commit_sha: str, branch: str) -> None:
    """anchor_updates: {anchor: status}, e.g. {'stack': 'skipped'}"""
    repo = get_repo()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        existing = repo.get_contents(TRACKING_INDEX_PATH, ref=branch)
        rows = _parse_tracking_rows(existing.decoded_content.decode())
    except Exception:
        rows = {}  # file doesn't exist yet — first run, start fresh

    for anchor, status in anchor_updates.items():  # merge this run's updates into whatever already existed
        rows[anchor] = {
            "section": anchor.replace("-", " ").title(),
            "status": status,
            "commit": commit_sha,
            "updated": now,
        }

    write_repo_file(
        path=TRACKING_INDEX_PATH,
        content=_render_tracking_index(rows),
        message=f"GitSteward: update tracking index (push {commit_sha[:7]})",
        branch=branch,
    )