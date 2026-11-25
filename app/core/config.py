"""Application configuration and environment normalization."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def normalize_database_url(url: str) -> str:
    """Normalize legacy postgres:// URLs to SQLAlchemy-compatible postgresql:// URLs."""
    cleaned = (url or "").strip()
    if cleaned.startswith("postgres://"):
        return "postgresql://" + cleaned[len("postgres://") :]
    return cleaned


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    APP_NAME: str = "Speech to Text"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    PORT: int = Field(default=8001, ge=1, le=65535)

    DATABASE_URL: str = (
        "postgresql://stt_user:stt_password@localhost:5432/speech_to_text_db"
    )

    WHISPER_MODEL: str = "small"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    HF_HOME: str = r"D:\AI-Models\huggingface"

    MAX_UPLOAD_MB: int = Field(default=25, ge=1, le=200)
    MAX_SESSION_SECONDS: int = Field(default=600, ge=10, le=3600)
    MAX_CONCURRENT_SESSIONS: int = Field(default=3, ge=1, le=50)
    FINAL_FULL_PASS_MAX_SEC: int = Field(default=60, ge=5, le=600)
    MAX_WS_FRAME_BYTES: int = Field(default=65536, ge=1024, le=1048576)

    ALLOWED_WS_ORIGINS: str = ""
    LOG_DIR: str = str(BASE_DIR / "logs")
    RATE_LIMIT_REQUESTS: int = Field(default=120, ge=10, le=5000)
    RATE_LIMIT_WINDOW_SEC: int = Field(default=60, ge=1, le=3600)

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_db_url(cls, value: str) -> str:
        return normalize_database_url(str(value))

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def allowed_ws_origins_list(self) -> List[str]:
        if not self.ALLOWED_WS_ORIGINS.strip():
            return []
        return [
            origin.strip().rstrip("/")
            for origin in self.ALLOWED_WS_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings and ensure HF_HOME is exported."""
    settings = Settings()
    if settings.HF_HOME:
        os.environ["HF_HOME"] = settings.HF_HOME
    return settings
