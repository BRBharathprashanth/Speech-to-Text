"""Transcription persistence, script-mix classification, CRUD, and stats service."""

from __future__ import annotations

import math
import unicodedata
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database.models import Transcription, utc_now
from app.schemas.transcription import (
    StatsResponse,
    TranscriptionCreate,
    TranscriptionUpdate,
)

logger = get_logger(__name__)


def classify_script_mix(text: str) -> str:
    """Classify text into 'hindi', 'english', 'mixed', or 'other' using Devanagari vs Latin letter ratios.

    Thresholds:
    - Fewer than 2 alphabetic Devanagari/Latin characters -> 'other'
    - At least 2 letters of each script and each >= 10% of total -> 'mixed'
    - Devanagari ratio >= 80% -> 'hindi'
    - Latin ratio >= 80% -> 'english'
    - Otherwise -> 'other'
    """
    if not text:
        return "other"

    devanagari_letters = 0
    latin_letters = 0

    for ch in text:
        cat = unicodedata.category(ch)
        if not cat.startswith("L"):
            continue
        code = ord(ch)
        if 0x0900 <= code <= 0x097F:
            devanagari_letters += 1
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z") or (0x00C0 <= code <= 0x024F):
            latin_letters += 1

    total_letters = devanagari_letters + latin_letters
    if total_letters < 2:
        return "other"

    dev_ratio = devanagari_letters / total_letters
    lat_ratio = latin_letters / total_letters

    if devanagari_letters >= 2 and latin_letters >= 2 and dev_ratio >= 0.10 and lat_ratio >= 0.10:
        return "mixed"
    if dev_ratio >= 0.80:
        return "hindi"
    if lat_ratio >= 0.80:
        return "english"
    return "other"


def create_transcription(
    db: Session, payload: TranscriptionCreate
) -> tuple[Transcription, bool]:
    """Create a transcription record, idempotently returning existing row when session_id matches."""
    if payload.session_id:
        existing = db.scalar(
            select(Transcription).where(Transcription.session_id == payload.session_id)
        )
        if existing is not None:
            return existing, False

    script_mix = classify_script_mix(payload.transcription_text)
    now = utc_now()
    record = Transcription(
        session_id=payload.session_id,
        transcription_text=payload.transcription_text,
        detected_language=payload.detected_language,
        script_mix=script_mix,
        audio_filename=payload.audio_filename,
        audio_format=payload.audio_format,
        audio_duration=payload.audio_duration,
        transcription_status=payload.transcription_status,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    try:
        db.commit()
        db.refresh(record)
        logger.info(
            "Saved transcription record",
            extra={
                "event": "db_transcription_created",
                "extra_data": {
                    "id": record.id,
                    "script_mix": record.script_mix,
                    "detected_language": record.detected_language,
                },
            },
        )
        return record, True
    except IntegrityError:
        db.rollback()
        if payload.session_id:
            existing = db.scalar(
                select(Transcription).where(
                    Transcription.session_id == payload.session_id
                )
            )
            if existing is not None:
                return existing, False
        raise


def get_transcription(db: Session, transcription_id: int) -> Optional[Transcription]:
    """Retrieve a single transcription record by ID."""
    return db.get(Transcription, transcription_id)


def list_transcriptions(
    db: Session,
    *,
    q: Optional[str] = None,
    script_mix: Optional[str] = None,
    language: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Transcription], int, int]:
    """Search and paginate transcription records ordered newest first."""
    stmt = select(Transcription)
    count_stmt = select(func.count(Transcription.id))

    filters = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Transcription.transcription_text.ilike(pattern),
                Transcription.audio_filename.ilike(pattern),
                Transcription.detected_language.ilike(pattern),
            )
        )
    if script_mix and script_mix.strip():
        filters.append(Transcription.script_mix == script_mix.strip().lower())
    if language and language.strip():
        filters.append(Transcription.detected_language.ilike(language.strip()))

    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    total = int(db.scalar(count_stmt) or 0)
    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
    offset = (page - 1) * page_size

    rows = list(
        db.scalars(
            stmt.order_by(Transcription.created_at.desc(), Transcription.id.desc())
            .offset(offset)
            .limit(page_size)
        ).all()
    )
    return rows, total, total_pages


def update_transcription(
    db: Session, transcription_id: int, payload: TranscriptionUpdate
) -> Optional[Transcription]:
    """Update an existing transcription record and refresh script_mix and updated_at."""
    record = db.get(Transcription, transcription_id)
    if record is None:
        return None

    if payload.transcription_text is not None:
        record.transcription_text = payload.transcription_text
        record.script_mix = classify_script_mix(payload.transcription_text)
    if payload.detected_language is not None:
        record.detected_language = payload.detected_language
    if payload.transcription_status is not None:
        record.transcription_status = payload.transcription_status

    record.updated_at = utc_now()
    db.commit()
    db.refresh(record)
    logger.info(
        "Updated transcription record",
        extra={
            "event": "db_transcription_updated",
            "extra_data": {"id": record.id, "script_mix": record.script_mix},
        },
    )
    return record


def delete_transcription(db: Session, transcription_id: int) -> bool:
    """Delete a transcription record by ID."""
    record = db.get(Transcription, transcription_id)
    if record is None:
        return False
    db.delete(record)
    db.commit()
    logger.info(
        "Deleted transcription record",
        extra={"event": "db_transcription_deleted", "extra_data": {"id": transcription_id}},
    )
    return True


def get_stats(db: Session) -> StatsResponse:
    """Compute actual counts by script_mix directly from PostgreSQL."""
    rows = db.execute(
        select(Transcription.script_mix, func.count(Transcription.id)).group_by(
            Transcription.script_mix
        )
    ).all()
    counts = {"hindi": 0, "english": 0, "mixed": 0, "other": 0}
    total = 0
    for mix, count in rows:
        c = int(count or 0)
        total += c
        if mix in counts:
            counts[mix] += c
        else:
            counts["other"] += c
    return StatsResponse(total=total, **counts)
