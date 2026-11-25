"""Fast unit tests for URL normalization, script_mix classification, overlap merge, and filename sanitization."""

from __future__ import annotations

from app.core.config import normalize_database_url
from app.services.audio_service import sanitize_filename
from app.services.streaming_service import merge_overlap_text, strip_overlapping_prefix
from app.services.transcription_service import classify_script_mix


def test_normalize_database_url() -> None:
    assert (
        normalize_database_url("postgres://user:pass@host:5432/dbname")
        == "postgresql://user:pass@host:5432/dbname"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host:5432/dbname")
        == "postgresql://user:pass@host:5432/dbname"
    )


def test_classify_script_mix() -> None:
    assert classify_script_mix("I am building a FastAPI speech application.") == "english"
    assert classify_script_mix("आज मुझे एक नया प्रोजेक्ट बनाना है।") == "hindi"
    assert (
        classify_script_mix(
            "आज मुझे machine learning का project complete करना है।"
        )
        == "mixed"
    )
    assert classify_script_mix("12345 !!!") == "other"
    assert classify_script_mix("") == "other"


def test_overlap_deduplication_and_merge() -> None:
    existing = "I am building a speech to text application"
    incoming = "speech to text application using Python and FastAPI"
    assert strip_overlapping_prefix(existing, incoming) == "using Python and FastAPI"
    assert (
        merge_overlap_text(existing, incoming)
        == "I am building a speech to text application using Python and FastAPI"
    )

    # Identical tail and head should not duplicate.
    assert merge_overlap_text("नमस्ते भारत", "नमस्ते भारत") == "नमस्ते भारत"

    # Mixed Hindi-English overlap deduplication.
    assert (
        merge_overlap_text("आज मुझे machine learning", "machine learning का project करना है")
        == "आज मुझे machine learning का project करना है"
    )


def test_sanitize_filename_prevents_traversal() -> None:
    assert sanitize_filename("../../etc/passwd.wav") == "passwd.wav"
    assert sanitize_filename(r"C:\Users\secret\my audio (1).mp3") == "my_audio_1_.mp3"
    assert sanitize_filename("") == "upload.wav"
