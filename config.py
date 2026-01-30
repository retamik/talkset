from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str

    proxyapi_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    backend_url: str = "http://127.0.0.1:8000"
    db_path: str = "talkset.db"
    batch_window_seconds: int = 6 * 60 * 60

    llm_provider: str = "proxyapi"  # proxyapi | openai
    llm_model: str = "gpt-3.5-turbo"


settings = Settings()
