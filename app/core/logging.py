"""Structured application logging without leaking secrets or private audio."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_CREDENTIAL_PATTERN = re.compile(
    r"(postgres(?:ql)?://[^:\s/]+:)([^@\s]+)(@)", re.IGNORECASE
)


def redact_sensitive(text: str) -> str:
    """Mask database passwords or bearer tokens if accidentally included."""
    if not text:
        return text
    return _CREDENTIAL_PATTERN.sub(r"\1***\3", text)


class StructuredFormatter(logging.Formatter):
    """Render log records as single-line structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive(record.getMessage()),
        }
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event
        extra_data = getattr(record, "extra_data", None)
        if isinstance(extra_data, dict):
            payload["data"] = {
                k: redact_sensitive(str(v)) if isinstance(v, str) else v
                for k, v in extra_data.items()
            }
        if record.exc_info:
            payload["exception"] = redact_sensitive(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(log_dir: str | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure root and application loggers for console and optional D: file output."""
    formatter = StructuredFormatter()
    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers to avoid duplicates across reloads/tests.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if log_dir:
        try:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path / "app.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            # In read-only or container environments without writable log_dir, stdout remains active.
            pass

    # Quiet noisy third-party debug logs while preserving warnings/errors.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    return logging.getLogger("speech_to_text")


def get_logger(name: str = "speech_to_text") -> logging.Logger:
    """Return a named application logger."""
    return logging.getLogger(name)
