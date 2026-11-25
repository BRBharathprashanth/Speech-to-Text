"""Self-hosted Faster-Whisper speech recognition service with serialized CPU inference."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Union

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

HINGLISH_INITIAL_PROMPT = (
    "Hindi and English mixed. नमस्ते, hello, मैं ठीक हूँ, thank you."
)


class SpeechModelError(Exception):
    """Raised when the Faster-Whisper model fails to load or run inference."""


@dataclass
class TranscriptionResult:
    text: str
    detected_language: Optional[str]
    language_probability: Optional[float]
    processing_time_sec: float


class SpeechService:
    """Manages a single Faster-Whisper model instance with thread-safe serialized CPU inference."""

    def __init__(self) -> None:
        self._model: Any = None
        self._status: str = "uninitialized"  # uninitialized | loading | ready | error
        self._error_message: Optional[str] = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._warmup_task: Optional[asyncio.Task[None]] = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    def set_model_for_testing(self, model: Any) -> None:
        """Inject a mock or stub model during unit/integration tests."""
        self._model = model
        self._status = "ready"
        self._error_message = None

    def _load_model_sync(self) -> None:
        with self._load_lock:
            if self._model is not None and self._status == "ready":
                return

            settings = get_settings()
            if settings.HF_HOME:
                os.environ["HF_HOME"] = settings.HF_HOME

            self._status = "loading"
            self._error_message = None
            start = time.perf_counter()
            logger.info(
                "Initializing Faster-Whisper model",
                extra={
                    "event": "model_init_start",
                    "extra_data": {
                        "model": settings.WHISPER_MODEL,
                        "device": settings.WHISPER_DEVICE,
                        "compute_type": settings.WHISPER_COMPUTE_TYPE,
                        "hf_home": settings.HF_HOME,
                    },
                },
            )
            try:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    settings.WHISPER_MODEL,
                    device=settings.WHISPER_DEVICE,
                    compute_type=settings.WHISPER_COMPUTE_TYPE,
                )
                self._status = "ready"
                elapsed = round(time.perf_counter() - start, 2)
                logger.info(
                    "Faster-Whisper model ready",
                    extra={
                        "event": "model_init_ready",
                        "extra_data": {
                            "model": settings.WHISPER_MODEL,
                            "elapsed_sec": elapsed,
                        },
                    },
                )
            except Exception as exc:
                self._model = None
                self._status = "error"
                self._error_message = f"Failed to load Whisper model ({type(exc).__name__})."
                logger.exception(
                    "Faster-Whisper model failed to initialize",
                    extra={"event": "model_init_error"},
                )

    def start_warmup(self) -> None:
        """Schedule non-blocking background warm-up on the event loop."""
        if self._status in {"loading", "ready"}:
            return
        if self._warmup_task is not None and not self._warmup_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._status = "loading"
            self._warmup_task = loop.create_task(self._warmup_async())
        except RuntimeError:
            # No running loop (e.g. synchronous script context).
            self._load_model_sync()

    async def _warmup_async(self) -> None:
        await asyncio.to_thread(self._load_model_sync)

    async def ensure_ready(self) -> None:
        """Ensure the model is loaded, waiting for active warm-up if needed."""
        if self._status == "ready" and self._model is not None:
            return
        if self._warmup_task is not None and not self._warmup_task.done():
            await self._warmup_task
        if self._status == "uninitialized":
            await asyncio.to_thread(self._load_model_sync)
        elif self._status == "loading":
            # Another caller is loading synchronously; wait via load lock in thread.
            await asyncio.to_thread(self._load_model_sync)

        if self._status != "ready" or self._model is None:
            raise SpeechModelError(
                self._error_message or "Speech recognition model is unavailable."
            )

    def _transcribe_sync(
        self,
        audio_input: Union[str, np.ndarray],
        *,
        beam_size: int = 1,
        vad_filter: bool = True,
    ) -> TranscriptionResult:
        if self._model is None:
            raise SpeechModelError("Speech recognition model is not loaded.")

        start = time.perf_counter()
        with self._infer_lock:
            segments, info = self._model.transcribe(
                audio_input,
                language=None,
                task="transcribe",
                vad_filter=vad_filter,
                beam_size=beam_size,
                condition_on_previous_text=False,
                initial_prompt=HINGLISH_INITIAL_PROMPT,
            )
            text_parts: list[str] = []
            for segment in segments:
                seg_text = (getattr(segment, "text", "") or "").strip()
                if seg_text:
                    text_parts.append(seg_text)

        elapsed = round(time.perf_counter() - start, 3)
        full_text = " ".join(text_parts).strip()
        detected_language = getattr(info, "language", None)
        lang_prob = getattr(info, "language_probability", None)
        return TranscriptionResult(
            text=full_text,
            detected_language=detected_language,
            language_probability=(
                round(float(lang_prob), 4) if lang_prob is not None else None
            ),
            processing_time_sec=elapsed,
        )

    async def transcribe(
        self,
        audio_input: Union[str, np.ndarray],
        *,
        beam_size: int = 1,
        vad_filter: bool = True,
    ) -> TranscriptionResult:
        """Run Faster-Whisper transcription in a worker thread without blocking the event loop."""
        await self.ensure_ready()
        return await asyncio.to_thread(
            self._transcribe_sync,
            audio_input,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )


_speech_service = SpeechService()


def get_speech_service() -> SpeechService:
    """Return the singleton SpeechService instance."""
    return _speech_service
