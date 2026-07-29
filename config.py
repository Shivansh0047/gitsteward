from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore") # Read .env and igonore any extra variable

    github_app_id: int # case-insensitive
    github_app_private_key_path: str
    github_webhook_secret: str
    github_installation_id: int

    demo_repo_owner: str = "Shivansh0047"
    demo_repo_name: str = "RAG-Chatbot-Service"


settings = Settings()