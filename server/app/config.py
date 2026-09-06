from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server configuration, read from the environment (and .env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["gemini", "openai", "deepseek", "kimi"] = "gemini"
    gemini_model: str = "gemini-3.1-flash-lite"
    openai_model: str = "gpt-5.6-luna"
    deepseek_model: str = "deepseek-v4-flash"
    kimi_model: str = "kimi-k2.6"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    moonshot_api_key: str = ""
    max_output_tokens: int = 4096
    knowledge_dir: Path = Path(__file__).resolve().parent.parent / "knowledge"
    rate_limit: str = "20 per 10 minutes"
    # Hard daily spend cap (USD); when reached the agent refuses politely
    # until midnight. 0 disables the cap.
    daily_budget_usd: float = 2.0
    # Bearer token for /api/admin/* (approving high-risk agent actions).
    # Empty disables the admin endpoints entirely.
    admin_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
