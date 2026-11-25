"""Real-time audio streaming buffer, word-level overlap deduplication, and session manager."""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.speech_service import SpeechService, get_speech_service

logger = get_logger(__name__)

PARTIAL_DECODE_INTERVAL_SEC = 1.5
MIN_DECODE_AUDIO_SEC = 0.8
COMMIT_WINDOW_SEC = 20.0
OVERLAP_TAIL_SEC = 2.0
SESSION_RESUME_TTL_SEC = 30.0

_TOKEN_CLEAN_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def _normalize_word(word: str) -> str:
    """Normalize a token for overlap matching across Latin and Devanagari scripts."""
    stripped = _TOKEN_CLEAN_RE.sub("", word)
    return unicodedata.normalize("NFC", stripped).casefold()


def strip_overlapping_prefix(existing_text: str, new_segment: str) -> str:
    """Remove leading words from new_segment that overlap with the tail of existing_text."""
    existing = (existing_text or "").strip()
    incoming = (new_segment or "").strip()
    if not existing or not incoming:
        return incoming

    existing_words = existing.split()
    incoming_words = incoming.split()
    max_k = min(14, len(existing_words), len(incoming_words))

    best_overlap = 0
    for k in range(max_k, 0, -1):
        tail_norm = [_normalize_word(w) for w in existing_words[-k:]]
        head_norm = [_normalize_word(w) for w in incoming_words[:k]]
        if any(not w for w in tail_norm) or any(not w for w in head_norm):
            continue
        if tail_norm == head_norm:
            # Avoid stripping a single short filler token unless multi-word or >= 3 chars.
            if k == 1 and len(head_norm[0]) < 3:
                continue
            best_overlap = k
            break

    if best_overlap == 0:
        return incoming
    return " ".join(incoming_words[best_overlap:]).strip()


def merge_overlap_text(existing_text: str, new_segment: str) -> str:
    """Merge new_segment onto existing_text while deduplicating overlapping boundary words."""
    existing = (existing_text or "").strip()
    incoming = (new_segment or "").strip()
    if not existing:
        return incoming
    if not incoming:
        return existing

    remainder = strip_overlapping_prefix(existing, incoming)
    if not remainder:
        return existing
    return f"{existing} {remainder}".strip()


@dataclass
class StreamingSession:
    """In-memory rolling audio and transcript state for a single WebSocket recording."""

    session_id: str
    sample_rate: int = 16000
    channels: int = 1
    created_monotonic: float = field(default_factory=time.monotonic)
    disconnected_monotonic: Optional[float] = None
    active: bool = True
    completed: bool = False

    rolling_pcm: bytearray = field(default_factory=bytearray)
    full_audio_pcm: Optional[bytearray] = field(default_factory=bytearray)
    total_pcm_bytes: int = 0
    bytes_since_last_decode: int = 0

    committed_text: str = ""
    partial_text: str = ""
    detected_language: Optional[str] = None
    saved_record_id: Optional[int] = None

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * 2  # int16 = 2 bytes/sample

    @property
    def total_duration_sec(self) -> float:
        if self.bytes_per_second <= 0:
            return 0.0
        return self.total_pcm_bytes / float(self.bytes_per_second)

    @property
    def rolling_duration_sec(self) -> float:
        if self.bytes_per_second <= 0:
            return 0.0
        return len(self.rolling_pcm) / float(self.bytes_per_second)

    def append_pcm(self, chunk: bytes, final_full_pass_max_sec: int) -> None:
        """Append signed 16-bit PCM frame and discard full buffer if exceeding full-pass limit."""
        # Align to whole 16-bit samples.
        usable_len = len(chunk) - (len(chunk) % 2)
        if usable_len <= 0:
            return
        data = chunk[:usable_len]
        self.rolling_pcm.extend(data)
        self.total_pcm_bytes += usable_len
        self.bytes_since_last_decode += usable_len

        if self.full_audio_pcm is not None:
            if self.total_duration_sec <= final_full_pass_max_sec:
                self.full_audio_pcm.extend(data)
            else:
                # Avoid unbounded memory growth on long sessions.
                self.full_audio_pcm = None

    @staticmethod
    def pcm16_to_float32(pcm_bytes: bytes | bytearray) -> np.ndarray:
        """Convert signed 16-bit little-endian PCM bytes to float32 [-1.0, 1.0]."""
        if not pcm_bytes:
            return np.zeros(0, dtype=np.float32)
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        return samples / 32768.0

    def should_decode_partial(self) -> bool:
        if self.rolling_duration_sec < MIN_DECODE_AUDIO_SEC:
            return False
        min_step_bytes = int(PARTIAL_DECODE_INTERVAL_SEC * self.bytes_per_second)
        return self.bytes_since_last_decode >= min_step_bytes

    def trim_rolling_with_overlap(self) -> None:
        """Keep only the overlap tail in rolling_pcm after committing a segment."""
        overlap_bytes = int(OVERLAP_TAIL_SEC * self.bytes_per_second)
        overlap_bytes -= overlap_bytes % 2
        if len(self.rolling_pcm) > overlap_bytes > 0:
            self.rolling_pcm = bytearray(self.rolling_pcm[-overlap_bytes:])
        else:
            self.rolling_pcm.clear()
        self.bytes_since_last_decode = 0


class StreamingSessionManager:
    """Tracks active and briefly-disconnected streaming sessions with concurrency limits."""

    def __init__(self) -> None:
        self._sessions: dict[str, StreamingSession] = {}
        self._lock = asyncio.Lock()

    def _prune_expired_locked(self) -> None:
        now = time.monotonic()
        expired_ids = [
            sid
            for sid, sess in self._sessions.items()
            if (
                not sess.active
                and sess.disconnected_monotonic is not None
                and (now - sess.disconnected_monotonic) > SESSION_RESUME_TTL_SEC
            )
            or sess.completed
        ]
        for sid in expired_ids:
            self._sessions.pop(sid, None)

    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.active and not s.completed)

    async def start_or_resume(
        self,
        session_id: str,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        resume: bool = False,
    ) -> tuple[Optional[StreamingSession], str]:
        """Start a new session or resume an unexpired disconnected session.

        Returns (session, status) where status is 'started' | 'resumed' | 'session_lost' | 'capacity_full'.
        """
        settings = get_settings()
        async with self._lock:
            self._prune_expired_locked()
            existing = self._sessions.get(session_id)

            if resume:
                if existing is not None and not existing.completed:
                    existing.active = True
                    existing.disconnected_monotonic = None
                    return existing, "resumed"
                return None, "session_lost"

            if existing is not None and not existing.completed:
                existing.active = True
                existing.disconnected_monotonic = None
                return existing, "resumed"

            if self.active_count() >= settings.MAX_CONCURRENT_SESSIONS:
                return None, "capacity_full"

            session = StreamingSession(
                session_id=session_id,
                sample_rate=sample_rate,
                channels=channels,
            )
            self._sessions[session_id] = session
            return session, "started"

    async def mark_disconnected(self, session_id: str) -> None:
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess is not None and not sess.completed:
                sess.active = False
                sess.disconnected_monotonic = time.monotonic()

    async def complete_and_remove(self, session_id: str) -> None:
        async with self._lock:
            sess = self._sessions.pop(session_id, None)
            if sess is not None:
                sess.active = False
                sess.completed = True
                sess.rolling_pcm.clear()
                sess.full_audio_pcm = None


_session_manager = StreamingSessionManager()


def get_session_manager() -> StreamingSessionManager:
    return _session_manager


async def process_rolling_window(
    session: StreamingSession,
    speech_service: Optional[SpeechService] = None,
) -> dict[str, Optional[str]]:
    """Decode current rolling buffer and either emit a partial update or commit a ~20s segment."""
    svc = speech_service or get_speech_service()
    audio_f32 = session.pcm16_to_float32(session.rolling_pcm)
    session.bytes_since_last_decode = 0
    if len(audio_f32) == 0:
        return {"event": "noop", "partial": session.partial_text, "committed": session.committed_text}

    result = await svc.transcribe(audio_f32, beam_size=1, vad_filter=True)
    if result.detected_language:
        session.detected_language = result.detected_language

    raw_text = result.text.strip()
    if session.rolling_duration_sec >= COMMIT_WINDOW_SEC:
        if raw_text:
            session.committed_text = merge_overlap_text(session.committed_text, raw_text)
        session.partial_text = ""
        session.trim_rolling_with_overlap()
        return {
            "event": "committed",
            "committed": session.committed_text,
            "partial": "",
            "detected_language": session.detected_language,
        }

    # Keep temporary partial separate from committed text without repeating overlap words.
    clean_partial = strip_overlapping_prefix(session.committed_text, raw_text)
    session.partial_text = clean_partial
    return {
        "event": "partial",
        "committed": session.committed_text,
        "partial": clean_partial,
        "detected_language": session.detected_language,
    }


async def finalize_session_audio(
    session: StreamingSession,
    speech_service: Optional[SpeechService] = None,
) -> tuple[str, Optional[str], float]:
    """Run full-audio final pass for short sessions, or tail-stitch for longer sessions."""
    svc = speech_service or get_speech_service()
    settings = get_settings()
    duration = round(session.total_duration_sec, 3)

    if duration < 0.1:
        return session.committed_text.strip(), session.detected_language, duration

    if (
        session.full_audio_pcm is not None
        and duration <= settings.FINAL_FULL_PASS_MAX_SEC
        and len(session.full_audio_pcm) > 0
    ):
        audio_f32 = session.pcm16_to_float32(session.full_audio_pcm)
        result = await svc.transcribe(audio_f32, beam_size=3, vad_filter=True)
        final_text = result.text.strip() or session.committed_text.strip()
        detected_lang = result.detected_language or session.detected_language
        return final_text, detected_lang, duration

    # Long recording: transcribe remaining unprocessed tail and stitch onto committed text.
    if len(session.rolling_pcm) >= int(0.2 * session.bytes_per_second):
        tail_f32 = session.pcm16_to_float32(session.rolling_pcm)
        result = await svc.transcribe(tail_f32, beam_size=3, vad_filter=True)
        merged = merge_overlap_text(session.committed_text, result.text)
        detected_lang = result.detected_language or session.detected_language
        return merged.strip(), detected_lang, duration

    return session.committed_text.strip(), session.detected_language, duration
