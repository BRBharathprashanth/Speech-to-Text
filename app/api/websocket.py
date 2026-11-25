"""WebSocket endpoint (/ws/transcribe) for real-time 16 kHz mono PCM streaming."""

from __future__ import annotations

import json
import time
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.connection import get_session_factory
from app.schemas.transcription import TranscriptionCreate, TranscriptionOut
from app.services.speech_service import SpeechModelError, get_speech_service
from app.services.streaming_service import (
    StreamingSession,
    finalize_session_audio,
    get_session_manager,
    process_rolling_window,
)
from app.services.transcription_service import create_transcription

logger = get_logger(__name__)
router = APIRouter()


def is_valid_ws_origin(websocket: WebSocket) -> bool:
    """Validate WebSocket Origin header against ALLOWED_WS_ORIGINS or request Host."""
    origin = websocket.headers.get("origin")
    if not origin:
        # Non-browser clients (e.g., CLI/pytest) may omit Origin.
        return True

    settings = get_settings()
    allowed = settings.allowed_ws_origins_list
    normalized_origin = origin.strip().rstrip("/")
    if allowed:
        return normalized_origin in allowed

    host = websocket.headers.get("host", "").strip()
    if not host:
        return False

    parsed = urlparse(normalized_origin)
    if parsed.scheme not in {"http", "https"}:
        return False

    origin_host = parsed.netloc
    if origin_host == host:
        return True

    # In local development, allow localhost and 127.0.0.1 variations on same port.
    if settings.APP_ENV == "development":
        host_name = host.split(":")[0]
        origin_name = (parsed.hostname or "")
        if host_name in {"localhost", "127.0.0.1"} and origin_name in {"localhost", "127.0.0.1"}:
            return True

    return False


async def _send_json(websocket: WebSocket, payload: dict[str, object]) -> None:
    await websocket.send_text(json.dumps(payload, ensure_ascii=False))


def _save_final_record(
    session: StreamingSession,
    final_text: str,
    detected_language: Optional[str],
    duration: float,
) -> Optional[TranscriptionOut]:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        record, _ = create_transcription(
            db,
            TranscriptionCreate(
                session_id=session.session_id,
                transcription_text=final_text,
                detected_language=detected_language,
                audio_filename=f"live_{session.session_id[:12]}.pcm",
                audio_format="pcm_s16le",
                audio_duration=duration,
                transcription_status="completed",
            ),
        )
        session.saved_record_id = record.id
        return TranscriptionOut.model_validate(record)
    finally:
        db.close()


@router.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket) -> None:
    """Handle real-time PCM audio streaming, partial updates, final pass, and persistence."""
    if not is_valid_ws_origin(websocket):
        logger.warning(
            "Rejected WebSocket connection due to invalid origin",
            extra={"event": "ws_origin_rejected"},
        )
        await websocket.close(code=1008, reason="Invalid WebSocket origin")
        return

    await websocket.accept()
    settings = get_settings()
    manager = get_session_manager()
    speech = get_speech_service()
    session: Optional[StreamingSession] = None
    graceful_stop = False

    logger.info("WebSocket client connected", extra={"event": "ws_connected"})

    try:
        while True:
            message = await websocket.receive()
            msg_type = message.get("type")
            if msg_type == "websocket.disconnect":
                break

            if "text" in message and message["text"] is not None:
                raw_text = message["text"].strip()
                if raw_text.lower() == "stop":
                    ctrl = {"type": "stop"}
                else:
                    try:
                        ctrl = json.loads(raw_text)
                    except json.JSONDecodeError:
                        await _send_json(
                            websocket,
                            {"type": "error", "message": "Invalid control message JSON."},
                        )
                        continue

                action = str(ctrl.get("type", "")).lower()
                if action == "start":
                    session_id = str(ctrl.get("session_id") or "").strip()
                    if not session_id or len(session_id) > 128:
                        await _send_json(
                            websocket,
                            {"type": "error", "message": "A valid session_id is required."},
                        )
                        await websocket.close(code=1008)
                        return

                    sample_rate = int(ctrl.get("sample_rate") or 16000)
                    channels = int(ctrl.get("channels") or 1)
                    if sample_rate != 16000 or channels != 1:
                        await _send_json(
                            websocket,
                            {
                                "type": "error",
                                "message": "Audio stream must be 16000 Hz mono signed 16-bit PCM.",
                            },
                        )
                        await websocket.close(code=1008)
                        return

                    resume = bool(ctrl.get("resume", False))
                    sess, status_code = await manager.start_or_resume(
                        session_id,
                        sample_rate=sample_rate,
                        channels=channels,
                        resume=resume,
                    )
                    if status_code == "capacity_full" or sess is None:
                        msg = (
                            "Server session state is no longer available. Please start a new recording."
                            if status_code == "session_lost"
                            else "Maximum concurrent recording sessions reached. Please try again shortly."
                        )
                        await _send_json(
                            websocket,
                            {"type": status_code if status_code == "session_lost" else "error", "message": msg},
                        )
                        await websocket.close(code=1013 if status_code == "capacity_full" else 1000)
                        return

                    session = sess
                    await _send_json(
                        websocket,
                        {
                            "type": status_code,
                            "session_id": session.session_id,
                            "committed_text": session.committed_text,
                            "duration_seconds": round(session.total_duration_sec, 2),
                        },
                    )
                    continue

                if action == "stop":
                    if session is None:
                        await _send_json(
                            websocket,
                            {"type": "error", "message": "Recording session was not started."},
                        )
                        continue

                    graceful_stop = True
                    try:
                        final_text, detected_lang, duration = await finalize_session_audio(
                            session, speech
                        )
                    except SpeechModelError as exc:
                        await _send_json(
                            websocket, {"type": "error", "message": str(exc)}
                        )
                        await manager.complete_and_remove(session.session_id)
                        await websocket.close(code=1011)
                        return

                    if not final_text:
                        await _send_json(
                            websocket,
                            {
                                "type": "final",
                                "session_id": session.session_id,
                                "text": "",
                                "record": None,
                                "message": "No recognizable speech detected.",
                            },
                        )
                        await manager.complete_and_remove(session.session_id)
                        await websocket.close(code=1000)
                        return

                    try:
                        saved = _save_final_record(
                            session, final_text, detected_lang, duration
                        )
                    except SQLAlchemyError as exc:
                        logger.error(
                            "Database error saving live transcription",
                            extra={
                                "event": "ws_db_error",
                                "extra_data": {"error_type": type(exc).__name__},
                            },
                        )
                        await _send_json(
                            websocket,
                            {
                                "type": "final",
                                "session_id": session.session_id,
                                "text": final_text,
                                "record": None,
                                "error": "Transcription completed, but database save failed.",
                            },
                        )
                        await manager.complete_and_remove(session.session_id)
                        await websocket.close(code=1011)
                        return

                    await _send_json(
                        websocket,
                        {
                            "type": "final",
                            "session_id": session.session_id,
                            "text": final_text,
                            "detected_language": detected_lang,
                            "audio_duration": duration,
                            "record_id": saved.id if saved else None,
                            "record": saved.model_dump(mode="json") if saved else None,
                        },
                    )
                    await manager.complete_and_remove(session.session_id)
                    await websocket.close(code=1000)
                    return

                await _send_json(
                    websocket,
                    {"type": "error", "message": f"Unsupported control message '{action}'."},
                )
                continue

            if "bytes" in message and message["bytes"] is not None:
                if session is None:
                    await _send_json(
                        websocket,
                        {"type": "error", "message": "Send a 'start' message before audio frames."},
                    )
                    continue

                frame = message["bytes"]
                if len(frame) > settings.MAX_WS_FRAME_BYTES:
                    await _send_json(
                        websocket,
                        {"type": "error", "message": "Audio frame exceeds maximum allowed size."},
                    )
                    await manager.complete_and_remove(session.session_id)
                    await websocket.close(code=1009)
                    return

                session.append_pcm(frame, settings.FINAL_FULL_PASS_MAX_SEC)
                elapsed_wall = time.monotonic() - session.created_monotonic
                if (
                    session.total_duration_sec > settings.MAX_SESSION_SECONDS
                    or elapsed_wall > settings.MAX_SESSION_SECONDS + 15
                ):
                    await _send_json(
                        websocket,
                        {"type": "error", "message": "Maximum recording duration exceeded."},
                    )
                    await manager.complete_and_remove(session.session_id)
                    await websocket.close(code=1000)
                    return

                if session.should_decode_partial():
                    try:
                        update = await process_rolling_window(session, speech)
                        if update["event"] == "partial":
                            await _send_json(
                                websocket,
                                {
                                    "type": "partial",
                                    "text": update["partial"] or "",
                                    "committed_text": update["committed"] or "",
                                    "detected_language": update["detected_language"],
                                },
                            )
                        elif update["event"] == "committed":
                            await _send_json(
                                websocket,
                                {
                                    "type": "committed",
                                    "committed_text": update["committed"] or "",
                                    "partial_text": "",
                                    "detected_language": update["detected_language"],
                                },
                            )
                    except SpeechModelError as exc:
                        await _send_json(
                            websocket, {"type": "error", "message": str(exc)}
                        )
                        await manager.complete_and_remove(session.session_id)
                        await websocket.close(code=1011)
                        return

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected", extra={"event": "ws_disconnected"})
    except Exception as exc:
        logger.exception(
            "Unexpected WebSocket error",
            extra={"event": "ws_error", "extra_data": {"error_type": type(exc).__name__}},
        )
        try:
            await _send_json(
                websocket,
                {"type": "error", "message": "Unexpected server streaming error."},
            )
        except Exception:
            pass
    finally:
        if session is not None and not graceful_stop:
            await manager.mark_disconnected(session.session_id)
