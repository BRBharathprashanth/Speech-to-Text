"""Fast audio upload validation and FFmpeg conversion tests (with stubbed Whisper)."""

from __future__ import annotations

import io
import math
import struct
import wave

from fastapi.testclient import TestClient

from app.core.config import get_settings


def _make_wav_bytes(duration_sec: float = 0.5, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    n_frames = int(duration_sec * sample_rate)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_frames):
            val = int(12000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def test_upload_valid_wav_transcribes_and_saves(client: TestClient) -> None:
    wav_data = _make_wav_bytes(0.6)
    res = client.post(
        "/api/transcribe",
        files={"file": ("../../evil/sample.wav", wav_data, "audio/wav")},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["record"]["audio_filename"] == "sample.wav"
    assert data["record"]["audio_format"] == "wav"
    assert data["record"]["audio_duration"] >= 0.5
    assert data["record"]["transcription_text"] == "Hello world from stub whisper"


def test_upload_rejects_invalid_extension(client: TestClient) -> None:
    res = client.post(
        "/api/transcribe",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )
    assert res.status_code == 400
    assert "Unsupported file extension" in res.json()["detail"]


def test_upload_rejects_empty_file(client: TestClient) -> None:
    res = client.post(
        "/api/transcribe",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_upload_rejects_corrupt_audio(client: TestClient) -> None:
    res = client.post(
        "/api/transcribe",
        files={"file": ("corrupt.wav", b"RIFF0000WAVEfmt_garbage_data", "audio/wav")},
    )
    assert res.status_code == 400


def test_upload_rejects_unsupported_mime_type(client: TestClient) -> None:
    res = client.post(
        "/api/transcribe",
        files={"file": ("fake.wav", b"hello", "text/html")},
    )
    assert res.status_code == 415


def test_upload_rejects_oversized_file(client: TestClient, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0)
    # Using negative/zero byte limit forces 413 for any non-empty upload.
    wav_data = _make_wav_bytes(0.2)
    res = client.post(
        "/api/transcribe",
        files={"file": ("big.wav", wav_data, "audio/wav")},
    )
    assert res.status_code == 413
