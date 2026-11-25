"""Slow integration tests using real Faster-Whisper models and real user recordings."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.speech_service import HINGLISH_INITIAL_PROMPT, SpeechService

AUDIO_DIR = Path(__file__).resolve().parent / "audio"
REQUIRED_FILES = ("en.wav", "hi.wav", "hinglish.wav")


def _audio_path(name: str) -> Path:
    path = AUDIO_DIR / name
    if not path.exists():
        pytest.skip(
            f"Real recording '{path}' not found. Provide en.wav, hi.wav, and hinglish.wav in tests/audio/."
        )
    return path


@pytest.mark.slow
@pytest.mark.parametrize("model_size", ["small", "medium"])
@pytest.mark.parametrize("filename", REQUIRED_FILES)
def test_real_audio_multilingual_models(model_size: str, filename: str, monkeypatch) -> None:
    audio_file = _audio_path(filename)
    monkeypatch.setenv("WHISPER_MODEL", model_size)

    from app.core.config import get_settings

    get_settings.cache_clear()
    service = SpeechService()
    service._load_model_sync()
    assert service.status == "ready"

    result = service._transcribe_sync(str(audio_file), beam_size=3, vad_filter=True)
    assert result.text.strip() != ""
    assert result.detected_language is not None
    print(
        f"[{model_size}] {filename} -> lang={result.detected_language} "
        f"time={result.processing_time_sec}s text={result.text!r}"
    )
    assert HINGLISH_INITIAL_PROMPT
