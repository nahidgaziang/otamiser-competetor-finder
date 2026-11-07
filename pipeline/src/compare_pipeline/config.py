from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Find project root and env files
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ENV_FILES = (
    str(_PROJECT_ROOT / ".env"),
    str(_PROJECT_ROOT / "web" / ".env"),
    ".env",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database Configuration
    DATABASE_URL: str = Field(
        default="postgresql://postgres@127.0.0.1:5432/otamiser_local"
    )
    DATABASE_URL_MIGRATOR: str = Field(
        default="postgresql://migrator@127.0.0.1:5432/otamiser_local"
    )
    DATABASE_URL_PIPELINE: str = Field(
        default="postgresql://pipeline_rw@127.0.0.1:5432/otamiser_local"
    )
    DATABASE_URL_WEB: str = Field(
        default="postgresql://web_app@127.0.0.1:5432/otamiser_local"
    )

    # AI Configuration (Spend cap $5.00 USD)
    ANTHROPIC_API_KEY: str = Field(default="")
    AI_SPEND_CAP_USD: float = Field(default=5.00)
    DEFAULT_MODEL: str = Field(default="claude-haiku-5-5")

    # Search & Crawling
    TAVILY_API_KEY: str = Field(default="")
    EXA_API_KEY: str = Field(default="")
    FIRECRAWL_API_KEY: str = Field(default="")

    # Webflow Safe Client Configuration
    WEBFLOW_MODE: Literal["off", "test"] = Field(default="off")
    WEBFLOW_API_TOKEN: str = Field(default="")
    WEBFLOW_SITE_ID: str = Field(default="")
    WEBFLOW_COLLECTION_ID: str = Field(default="")

    # Auth & Slack
    BETTER_AUTH_SECRET: str = Field(default="")
    BETTER_AUTH_URL: str = Field(default="http://127.0.0.1:4321")
    SLACK_WEBHOOK_URL: str = Field(default="")


settings = Settings()
