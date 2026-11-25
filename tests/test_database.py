"""Database persistence, unique constraint, and timestamp tests."""

from __future__ import annotations

import time

from app.database.connection import get_session_factory
from app.schemas.transcription import TranscriptionCreate, TranscriptionUpdate
from app.services.transcription_service import (
    create_transcription,
    get_transcription,
    update_transcription,
)


def test_idempotent_session_id_and_persistence() -> None:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        r1, created1 = create_transcription(
            db,
            TranscriptionCreate(
                session_id="unique-session-123",
                transcription_text="Hello testing persistence",
                detected_language="en",
            ),
        )
        r2, created2 = create_transcription(
            db,
            TranscriptionCreate(
                session_id="unique-session-123",
                transcription_text="Duplicate should return existing",
                detected_language="en",
            ),
        )
        assert created1 is True
        assert created2 is False
        assert r1.id == r2.id
        assert r2.transcription_text == "Hello testing persistence"
    finally:
        db.close()

    # Re-open a fresh DB session to verify persistence.
    db2 = session_factory()
    try:
        fetched = get_transcription(db2, r1.id)
        assert fetched is not None
        assert fetched.session_id == "unique-session-123"
        assert fetched.created_at.tzinfo is not None or fetched.created_at is not None
    finally:
        db2.close()


def test_updated_at_advances_on_edit() -> None:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        rec, _ = create_transcription(
            db,
            TranscriptionCreate(
                transcription_text="Initial English text",
                detected_language="en",
            ),
        )
        old_updated = rec.updated_at
        time.sleep(0.02)
        updated = update_transcription(
            db,
            rec.id,
            TranscriptionUpdate(transcription_text="आज मुझे project complete करना है"),
        )
        assert updated is not None
        assert updated.script_mix == "mixed"
        assert updated.updated_at > old_updated
    finally:
        db.close()
