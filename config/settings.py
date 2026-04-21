"""Pydantic Settings configuration for LocalDevin."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings can be overridden via environment variables with the ``LD_``
    prefix (e.g. ``LD_MAIN_MODEL``).
    """

    # LLM 設定
    ollama_base_url: str = "http://localhost:11434"
    main_model: str = "qwen3.6:35b-a3b-q4_K_M"
    fast_model: str = "qwen3.5:9b"
    vision_model: str = "gemma4:26b"
    context_length: int = 32768
    temperature: float = 0.1

    # 安全設定
    max_consecutive_errors: int = 3
    max_session_tokens: int = 500_000
    sandbox_memory_limit: str = "4g"
    sandbox_cpu_limit: float = 2.0

    # GitHub 設定
    github_token: str = ""
    github_default_branch: str = "main"
    pr_branch_prefix: str = "localdevin/"

    # パス設定
    knowledge_dir: str = "./knowledge"
    playbooks_dir: str = "./playbooks"
    db_path: str = "./data/sessions.db"
    chroma_path: str = "./data/chroma"

    # Slack 設定（オプション）
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_channel: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="LD_")


def get_settings() -> Settings:
    """Return a cached Settings instance.

    Returns:
        Settings: The application settings.
    """
    return Settings()
