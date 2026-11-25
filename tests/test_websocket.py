"""Fast WebSocket streaming, limits, origin validation, and reconnection tests."""

from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings


def _pcm_silence_frame(num_samples: int) -> bytes:
    return struct.pack("<" + "h" * num_samples, *([0] * num_samples))


def test_websocket_streaming_partial_and_final_save(client: TestClient) -> None:
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json(
            {
                "type": "start",
                "session_id": "ws-sess-001",
                "sample_rate": 16000,
                "channels": 1,
            }
        )
        start_msg = ws.receive_json()
        assert start_msg["type"] == "started"

        # Send 1.6s of PCM (25,600 samples) in chunks to trigger partial decode.
        for _ in range(8):
            ws.send_bytes(_pcm_silence_frame(3200))

        partial_msg = ws.receive_json()
        assert partial_msg["type"] == "partial"
        assert partial_msg["text"] == "Hello world from stub whisper"

        ws.send_json({"type": "stop"})
        final_msg = ws.receive_json()
        assert final_msg["type"] == "final"
        assert final_msg["record_id"] is not None
        assert final_msg["text"] == "Hello world from stub whisper"


def test_websocket_rejects_invalid_origin(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/transcribe", headers={"Origin": "https://evil.example.com"}
        ) as ws:
            ws.receive_text()


def test_websocket_rejects_oversized_frame(client: TestClient) -> None:
    settings = get_settings()
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json(
            {
                "type": "start",
                "session_id": "ws-sess-oversize",
                "sample_rate": 16000,
                "channels": 1,
            }
        )
        assert ws.receive_json()["type"] == "started"
        ws.send_bytes(b"\x00" * (settings.MAX_WS_FRAME_BYTES + 10))
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "maximum allowed size" in err["message"].lower()


def test_websocket_enforces_max_session_duration(
    client: TestClient, monkeypatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "MAX_SESSION_SECONDS", 1)
    with client.websocket_connect("/ws/transcribe") as ws:
        ws.send_json(
            {
                "type": "start",
                "session_id": "ws-sess-maxlen",
                "sample_rate": 16000,
                "channels": 1,
            }
        )
        assert ws.receive_json()["type"] == "started"
        # Send > 1 second (20,000 samples = 1.25s).
        ws.send_bytes(_pcm_silence_frame(20000))
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "maximum recording duration exceeded" in err["message"].lower()


def test_websocket_enforces_max_concurrent_sessions(
    client: TestClient, monkeypatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "MAX_CONCURRENT_SESSIONS", 1)
    with client.websocket_connect("/ws/transcribe") as ws1:
        ws1.send_json(
            {"type": "start", "session_id": "ws-c1", "sample_rate": 16000, "channels": 1}
        )
        assert ws1.receive_json()["type"] == "started"

        with client.websocket_connect("/ws/transcribe") as ws2:
            ws2.send_json(
                {"type": "start", "session_id": "ws-c2", "sample_rate": 16000, "channels": 1}
            )
            err = ws2.receive_json()
            assert err["type"] == "error"
            assert "maximum concurrent" in err["message"].lower()

        ws1.send_json({"type": "stop"})
        ws1.receive_json()


def test_websocket_resume_and_session_lost(client: TestClient) -> None:
    with client.websocket_connect("/ws/transcribe") as ws1:
        ws1.send_json(
            {"type": "start", "session_id": "ws-resume-1", "sample_rate": 16000, "channels": 1}
        )
        assert ws1.receive_json()["type"] == "started"
        ws1.send_bytes(_pcm_silence_frame(3200))
    # Unexpected disconnect keeps session in memory for grace TTL; reconnect resumes.
    with client.websocket_connect("/ws/transcribe") as ws2:
        ws2.send_json(
            {
                "type": "start",
                "session_id": "ws-resume-1",
                "sample_rate": 16000,
                "channels": 1,
                "resume": True,
            }
        )
        resumed = ws2.receive_json()
        assert resumed["type"] == "resumed"
        assert resumed["duration_seconds"] >= 0.19
        ws2.send_json({"type": "stop"})
        final_msg = ws2.receive_json()
        assert final_msg["type"] == "final"

    # Unknown / expired session reports session_lost honestly.
    with client.websocket_connect("/ws/transcribe") as ws3:
        ws3.send_json(
            {
                "type": "start",
                "session_id": "non-existent-session",
                "sample_rate": 16000,
                "channels": 1,
                "resume": True,
            }
        )
        lost = ws3.receive_json()
        assert lost["type"] == "session_lost"
