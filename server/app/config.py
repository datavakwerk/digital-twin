from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server configuration, read from the environment (and .env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model: str = "gemini-3.1-flash-lite"
    max_output_tokens: int = 4096
    knowledge_dir: Path = Path(__file__).resolve().parent.parent / "knowledge"


@lru_cache
def get_settings() -> Settings:
    return Settings()