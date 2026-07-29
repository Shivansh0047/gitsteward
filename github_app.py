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