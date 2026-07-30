from github import Github, GithubIntegration

from config import settings


def _load_private_key() -> str: # read .pem file
    with open(settings.github_app_private_key_path, "r") as f:
        return f.read()


def get_installation_client() -> Github:
    integration = GithubIntegration(settings.github_app_id, _load_private_key()) # Object of TestForge, the App, signs jwt token
    access_token = integration.get_access_token(settings.github_installation_id) # Exchnage KWT for real token
    return Github(access_token.token) # A normal PyGithub client already authicanted


def get_repo():
    client = get_installation_client()
    return client.get_repo(f"{settings.demo_repo_owner}/{settings.demo_repo_name}")


REVIEW_BRANCH = "test-forge/doc-suggestions"

# Create new revier branch or get the old one
def get_or_create_review_branch(base: str = "main") -> tuple[str, bool]:
    repo = get_repo()

    open_prs = repo.get_pulls(state="open", head=f"{repo.owner.login}:{REVIEW_BRANCH}") # Check if there is some brnch which alread exicts
    for pr in open_prs:
        return REVIEW_BRANCH, False  # reuse — already open, just add to it

    base_sha = repo.get_branch(base).commit.sha  # where main currently points
    repo.create_git_ref(ref=f"refs/heads/{REVIEW_BRANCH}", sha=base_sha)  # Name the branch after pointer of commit of main
    return REVIEW_BRANCH, True

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
    pr = repo.create_pull(title=title, body=body, head=branch, base=base) # Create PR
    return pr.number # return PR number

# A helper functin to mention this is a TestForge commit
def post_commit_comment(sha: str, body: str) -> None:
    repo = get_repo()
    commit = repo.get_commit(sha)
    commit.create_comment(body)