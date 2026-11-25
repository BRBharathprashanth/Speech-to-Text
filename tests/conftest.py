"""Shared pytest fixtures for fast unit/API tests with stubbed Faster-Whisper."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient

# Point fast tests to an isolated test DB unless TEST_DATABASE_URL is explicitly provided.
TEST_TMP_DIR = Path(__file__).resolve().parent.parent / "tmp"
TEST_TMP_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_TEST_DB = f"sqlite:///{(TEST_TMP_DIR / 'test_suite.db').as_posix()}"

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
os.environ["APP_ENV"] = "test"
os.environ["LOG_DIR"] = str(TEST_TMP_DIR / "logs")

from app.core.config import get_settings  # noqa: E402
from app.database.connection import get_engine, get_session_factory, init_engine  # noqa: E402
from app.database.models import Base, Transcription  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.speech_service import get_speech_service  # noqa: E402


@dataclass
class _StubSegment:
    text: str


@dataclass
class _StubInfo:
    language: str = "en"
    language_probability: float = 0.98


class StubWhisperModel:
    """Fast deterministic WhisperModel stub for non-slow tests."""

    def __init__(self, default_text: str = "Hello world from stub whisper", language: str = "en") -> None:
        self.default_text = default_text
        self.language = language
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio_input: Any, **kwargs: Any):
        self.calls.append({"audio_input": audio_input, **kwargs})
        return [_StubSegment(text=self.default_text)], _StubInfo(language=self.language)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database() -> Generator[None, None, None]:
    get_settings.cache_clear()
    settings = get_settings()
    engine = init_engine(settings.DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_transcriptions_table() -> Generator[None, None, None]:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        db.query(Transcription).delete()
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture()
def stub_whisper() -> StubWhisperModel:
    stub = StubWhisperModel()
    speech = get_speech_service()
    speech.set_model_for_testing(stub)
    return stub


@pytest.fixture()
def client(stub_whisper: StubWhisperModel) -> Generator[TestClient, None, None]:
    app = create_app(enable_model_warmup=False)
    with TestClient(app) as test_client:
        # Ensure engine stays bound to the test DB URL.
        init_engine(get_settings().DATABASE_URL)
        get_speech_service().set_model_for_testing(stub_whisper)
        yield test_client
