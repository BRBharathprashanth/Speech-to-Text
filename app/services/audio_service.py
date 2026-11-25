"""Audio upload validation, filename sanitization, and FFmpeg 16 kHz mono WAV conversion."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}

ALLOWED_AUDIO_MIME_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/vnd.wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/aac",
    "audio/flac",
    "audio/x-flac",
    "audio/ogg",
    "application/ogg",
    "audio/webm",
    "video/webm",
    "application/octet-stream",
}

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class AudioValidationError(Exception):
    """Structured error raised when uploaded audio fails validation or decoding."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class PreparedAudio:
    """Validated and FFmpeg-normalized 16 kHz mono WAV file inside a managed temp directory."""

    temp_dir: Path
    wav_path: Path
    sanitized_filename: str
    audio_format: str
    duration_seconds: float

    def cleanup(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)


def sanitize_filename(filename: Optional[str]) -> str:
    """Strip directory traversal components and sanitize uploaded filename."""
    if not filename:
        return "upload.wav"
    # Handle both Windows and POSIX path separators safely.
    base = filename.replace("\\", "/").split("/")[-1].strip()
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._")
    if not cleaned:
        return "upload.wav"
    if len(cleaned) > 180:
        stem = Path(cleaned).stem[:140]
        ext = Path(cleaned).suffix[:20]
        cleaned = f"{stem}{ext}"
    return cleaned


def validate_extension_and_mime(
    filename: Optional[str], content_type: Optional[str]
) -> tuple[str, str]:
    """Validate file extension and MIME type when provided."""
    sanitized = sanitize_filename(filename)
    ext = Path(sanitized).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise AudioValidationError(
            f"Unsupported file extension '{ext or 'none'}'. Allowed: WAV, MP3, M4A, FLAC, OGG, WebM.",
            status_code=400,
        )

    if content_type:
        mime = content_type.split(";")[0].strip().lower()
        if mime and mime not in ALLOWED_AUDIO_MIME_TYPES and not mime.startswith("audio/"):
            raise AudioValidationError(
                f"Unsupported audio MIME type '{mime}'.",
                status_code=415,
            )

    return sanitized, ext.lstrip(".")


def _has_known_audio_header(data: bytes, ext: str) -> bool:
    """Quick magic-byte sanity check before invoking ffprobe/ffmpeg."""
    if len(data) < 12:
        return False
    if ext == "wav":
        return data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if ext == "flac":
        return data[:4] == b"fLaC"
    if ext == "ogg":
        return data[:4] == b"OggS"
    if ext == "mp3":
        return data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)
    if ext == "m4a":
        return data[4:8] == b"ftyp"
    if ext == "webm":
        return data[:4] == b"\x1a\x45\xdf\xa3"
    return False


def _probe_audio_stream(input_path: Path) -> float:
    """Run ffprobe to verify an actual audio stream exists and return duration if available."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type,codec_name:format=duration",
        "-of",
        "json",
        str(input_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AudioValidationError(
            "FFprobe/FFmpeg is not available on the server.", status_code=500
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioValidationError(
            "Audio inspection timed out.", status_code=400
        ) from exc

    if proc.returncode != 0:
        raise AudioValidationError(
            "Invalid or corrupt audio file.", status_code=400
        )

    try:
        info = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AudioValidationError(
            "Unable to parse audio stream metadata.", status_code=400
        ) from exc

    streams = info.get("streams") or []
    if not streams or streams[0].get("codec_type") != "audio":
        raise AudioValidationError(
            "Uploaded file does not contain a valid audio stream.", status_code=400
        )

    raw_duration = (info.get("format") or {}).get("duration")
    try:
        return float(raw_duration) if raw_duration is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def convert_to_16k_mono_wav(input_path: Path, output_path: Path) -> float:
    """Convert any supported audio file to 16 kHz mono signed 16-bit PCM WAV via FFmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AudioValidationError(
            "FFmpeg is not available on the server.", status_code=500
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioValidationError(
            "Audio conversion timed out.", status_code=400
        ) from exc

    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 44:
        raise AudioValidationError(
            "Failed to decode audio file; the file may be corrupt or empty.",
            status_code=400,
        )

    try:
        with wave.open(str(output_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if frames <= 0 or rate <= 0:
                raise AudioValidationError("Audio file contains no playable frames.", status_code=400)
            duration = frames / float(rate)
    except wave.Error as exc:
        raise AudioValidationError("Converted audio stream is invalid.", status_code=400) from exc

    if duration < 0.05:
        raise AudioValidationError("Audio duration is too short or empty.", status_code=400)

    return round(duration, 3)


async def validate_and_prepare_upload(upload: UploadFile) -> PreparedAudio:
    """Stream-validate an uploaded audio file, check size & format, and convert to 16 kHz mono WAV."""
    settings = get_settings()
    sanitized, audio_format = validate_extension_and_mime(
        upload.filename, upload.content_type
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="stt_upload_"))
    raw_path = temp_dir / f"source.{audio_format}"
    wav_path = temp_dir / "normalized_16k.wav"

    try:
        total_bytes = 0
        header_bytes = bytearray()
        chunk_size = 256 * 1024
        max_bytes = settings.max_upload_bytes

        with raw_path.open("wb") as out_file:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise AudioValidationError(
                        f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_MB} MB.",
                        status_code=413,
                    )
                if len(header_bytes) < 64:
                    header_bytes.extend(chunk[: 64 - len(header_bytes)])
                out_file.write(chunk)

        if total_bytes == 0:
            raise AudioValidationError("Uploaded audio file is empty.", status_code=400)

        # Reject obvious plain-text/HTML/fake payloads early, while still verifying via ffprobe.
        if not _has_known_audio_header(bytes(header_bytes), audio_format):
            logger.info(
                "Header check did not match standard signature; verifying with ffprobe",
                extra={"event": "audio_header_fallback", "extra_data": {"format": audio_format}},
            )

        _probe_audio_stream(raw_path)
        duration = convert_to_16k_mono_wav(raw_path, wav_path)

        logger.info(
            "Prepared uploaded audio",
            extra={
                "event": "audio_prepared",
                "extra_data": {
                    "format": audio_format,
                    "size_bytes": total_bytes,
                    "duration_sec": duration,
                },
            },
        )
        return PreparedAudio(
            temp_dir=temp_dir,
            wav_path=wav_path,
            sanitized_filename=sanitized,
            audio_format=audio_format,
            duration_seconds=duration,
        )
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
