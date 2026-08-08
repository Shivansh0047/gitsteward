from github import Github, GithubIntegration
from github import GithubException  # need this to catch the specific "branch not found" error
from config import settings

from datetime import datetime, timezone

from github import InputGitTreeElement  # needed for batched multi-file commits

# To commit many files
def commit_multiple_files(branch: str, files: dict[str, str], message: str) -> None:
    """Writes several files in ONE commit, instead of one commit per file."""
    repo = get_repo()
    ref = repo.get_git_ref(f"heads/{branch}")
    base_commit = repo.get_git_commit(ref.object.sha)  # current tip of the branch

    elements = []
    for path, content in files.items():
        blob = repo.create_git_blob(content, "utf-8")  # raw file content, not yet attached anywhere
        elements.append(InputGitTreeElement(path=path, mode="100644", type="blob", sha=blob.sha))

    new_tree = repo.create_git_tree(elements, base_tree=base_commit.tree)  # snapshot of all files together
    new_commit = repo.create_git_commit(message, new_tree, [base_commit])  # one commit, parent = old tip
    ref.edit(new_commit.sha)  # move the branch pointer forward to the new commit

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
        return REVIEW_BRANCH, False, pr.number  # reuse — already open, just add to it, also returns pr number to be used later

    # no open PR, but does the branch itself still exist (leftover from a
    # merged/closed PR that was never cleaned up)? If so, delete it so we can
    # safely create a fresh one below — a stale branch with no open PR is dead weight.
    try:
        stale_ref = repo.get_git_ref(f"heads/{REVIEW_BRANCH}")
        stale_ref.delete()  # remove the leftover branch before recreating it
    except GithubException:
        pass  # branch genuinely doesn't exist — nothing to clean up, that's fine

    base_sha = repo.get_branch(base).commit.sha  # where main currently points
    repo.create_git_ref(ref=f"refs/heads/{REVIEW_BRANCH}", sha=base_sha)  # Name the branch after pointer of commit of main
    return REVIEW_BRANCH, True, None

def get_commit_diffs(sha: str) -> dict[str, str]: # Get actual code difference, so LLM can reason Properly
    """Returns {file_path: unified_diff_patch} for every file changed in this commit."""
    repo = get_repo()
    commit = repo.get_commit(sha)
    return {f.filename: f.patch for f in commit.files if f.patch}  # f.patch is None for binary/huge files

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
    for anchor in sorted(rows): # sorted = stable, predictable order across runs
        r = rows[anchor]
        lines += [
            f"## {r['section']} (#{anchor})",
            f"Status: {r['status']}",
            f"Commit: {r['commit'][:7]}", # short SHA, matches GitHub's own convention
            f"Updated: {r['updated']}",
            f"Summary: {r.get('summary', '-')}",   # new — placeholder "-" for old entries missing it
            "", # blank line between blocks
        ]
    return "\n".join(lines) + "\n"

def build_tracking_index_content(anchor_updates: dict[str, str], commit_sha: str, branch: str, summaries: dict[str, str] | None = None) -> str:
    """fetches the current file (if any), merges in this run's new anchor statuses, returns the content instead of writing it — caller batches the write."""
    summaries = summaries or {}
    repo = get_repo()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        existing = repo.get_contents(TRACKING_INDEX_PATH, ref=branch)
        rows = _parse_tracking_rows(existing.decoded_content.decode())
    except Exception:
        rows = {}

    for anchor, status in anchor_updates.items():
        rows[anchor] = {
            "section": anchor.replace("-", " ").title(),
            "status": status,
            "commit": commit_sha,
            "updated": now,
            "summary": summaries.get(anchor, "-"),
        }

    return _render_tracking_index(rows)  # just return it now, don't write