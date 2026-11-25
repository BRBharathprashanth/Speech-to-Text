"""SQLAlchemy 2 ORM models for transcription persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Transcription(Base):
    """Stored speech-to-text transcription record."""

    __tablename__ = "transcriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[Optional[str]] = mapped_column(
        String(128), unique=True, nullable=True
    )
    transcription_text: Mapped[str] = mapped_column(Text, nullable=False)
    detected_language: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    script_mix: Mapped[str] = mapped_column(
        String(16), nullable=False, default="other"
    )
    audio_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    audio_format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    audio_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    transcription_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="completed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_transcriptions_created_at", "created_at"),
        Index("ix_transcriptions_session_id", "session_id"),
        Index("ix_transcriptions_script_mix", "script_mix"),
    )
