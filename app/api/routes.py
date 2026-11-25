"""HTTP API routes for frontend, health, upload transcription, CRUD, stats, and languages."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.connection import check_db_health, get_db
from app.schemas.transcription import (
    DbHealthResponse,
    HealthResponse,
    LanguageInfoResponse,
    StatsResponse,
    TranscriptionCreate,
    TranscriptionListResponse,
    TranscriptionOut,
    TranscriptionUpdate,
    UploadTranscriptionResponse,
)
from app.services.audio_service import AudioValidationError, validate_and_prepare_upload
from app.services.speech_service import SpeechModelError, get_speech_service
from app.services.transcription_service import (
    create_transcription,
    delete_transcription,
    get_stats,
    get_transcription,
    list_transcriptions,
    update_transcription,
)

logger = get_logger(__name__)

router = APIRouter()
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard(request: Request) -> HTMLResponse:
    """Serve the Speech-to-Text dashboard."""
    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.APP_NAME,
            "max_upload_mb": settings.MAX_UPLOAD_MB,
            "max_session_seconds": settings.MAX_SESSION_SECONDS,
        },
    )


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Return application and Faster-Whisper model initialization status."""
    settings = get_settings()
    speech = get_speech_service()
    return HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        model_name=settings.WHISPER_MODEL,
        model_device=settings.WHISPER_DEVICE,
        model_compute_type=settings.WHISPER_COMPUTE_TYPE,
        model_status=speech.status,
        model_error=speech.error_message,
    )


@router.get("/health/db", response_model=DbHealthResponse, tags=["Health"])
async def db_health_check() -> DbHealthResponse:
    """Verify PostgreSQL connectivity via SELECT 1."""
    ok, detail = check_db_health()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )
    return DbHealthResponse(status="ok", database="connected", detail="ok")


@router.post(
    "/api/transcribe",
    response_model=UploadTranscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Transcription"],
)
async def upload_and_transcribe(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadTranscriptionResponse:
    """Validate an uploaded audio file, normalize via FFmpeg, transcribe via Faster-Whisper, and save to PostgreSQL."""
    prepared = None
    try:
        prepared = await validate_and_prepare_upload(file)
        speech = get_speech_service()
        result = await speech.transcribe(
            str(prepared.wav_path),
            beam_size=3,
            vad_filter=True,
        )
        if not result.text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No recognizable speech detected in the uploaded audio.",
            )

        record, _ = create_transcription(
            db,
            TranscriptionCreate(
                transcription_text=result.text,
                detected_language=result.detected_language,
                audio_filename=prepared.sanitized_filename,
                audio_format=prepared.audio_format,
                audio_duration=prepared.duration_seconds,
                transcription_status="completed",
            ),
        )
        return UploadTranscriptionResponse(
            record=TranscriptionOut.model_validate(record),
            processing_time_sec=result.processing_time_sec,
        )
    except AudioValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except SpeechModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except SQLAlchemyError as exc:
        logger.error(
            "Database failure while saving upload transcription",
            extra={"event": "db_error", "extra_data": {"error_type": type(exc).__name__}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable while saving transcription.",
        ) from exc
    finally:
        await file.close()
        if prepared is not None:
            prepared.cleanup()


@router.post(
    "/api/transcriptions",
    response_model=TranscriptionOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Transcriptions"],
)
async def create_transcription_endpoint(
    payload: TranscriptionCreate,
    db: Session = Depends(get_db),
) -> TranscriptionOut:
    """Create and persist a transcription record (idempotent when session_id matches)."""
    try:
        record, _ = create_transcription(db, payload)
        return TranscriptionOut.model_validate(record)
    except SQLAlchemyError as exc:
        logger.error(
            "Database error creating transcription",
            extra={"event": "db_error", "extra_data": {"error_type": type(exc).__name__}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from exc


@router.get(
    "/api/transcriptions",
    response_model=TranscriptionListResponse,
    tags=["Transcriptions"],
)
async def list_transcriptions_endpoint(
    q: Optional[str] = Query(default=None, max_length=200),
    script_mix: Optional[str] = Query(default=None, pattern="^(hindi|english|mixed|other)$"),
    language: Optional[str] = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TranscriptionListResponse:
    """Search and paginate stored transcription records."""
    try:
        rows, total, total_pages = list_transcriptions(
            db,
            q=q,
            script_mix=script_mix,
            language=language,
            page=page,
            page_size=page_size,
        )
        return TranscriptionListResponse(
            items=[TranscriptionOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    except SQLAlchemyError as exc:
        logger.error(
            "Database error listing transcriptions",
            extra={"event": "db_error", "extra_data": {"error_type": type(exc).__name__}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from exc


@router.get(
    "/api/transcriptions/{transcription_id}",
    response_model=TranscriptionOut,
    tags=["Transcriptions"],
)
async def get_transcription_endpoint(
    transcription_id: int,
    db: Session = Depends(get_db),
) -> TranscriptionOut:
    """Retrieve a single transcription record by ID."""
    try:
        record = get_transcription(db, transcription_id)
    except SQLAlchemyError as exc:
        logger.error(
            "Database error reading transcription",
            extra={"event": "db_error", "extra_data": {"error_type": type(exc).__name__}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found.",
        )
    return TranscriptionOut.model_validate(record)


@router.put(
    "/api/transcriptions/{transcription_id}",
    response_model=TranscriptionOut,
    tags=["Transcriptions"],
)
async def update_transcription_endpoint(
    transcription_id: int,
    payload: TranscriptionUpdate,
    db: Session = Depends(get_db),
) -> TranscriptionOut:
    """Update a transcription record and recalculate script_mix."""
    try:
        record = update_transcription(db, transcription_id, payload)
    except SQLAlchemyError as exc:
        logger.error(
            "Database error updating transcription",
            extra={"event": "db_error", "extra_data": {"error_type": type(exc).__name__}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found.",
        )
    return TranscriptionOut.model_validate(record)


@router.delete(
    "/api/transcriptions/{transcription_id}",
    status_code=status.HTTP_200_OK,
    tags=["Transcriptions"],
)
async def delete_transcription_endpoint(
    transcription_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Delete a transcription record by ID."""
    try:
        deleted = delete_transcription(db, transcription_id)
    except SQLAlchemyError as exc:
        logger.error(
            "Database error deleting transcription",
            extra={"event": "db_error", "extra_data": {"error_type": type(exc).__name__}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcription not found.",
        )
    return {"deleted": True, "id": transcription_id}


@router.get("/api/stats", response_model=StatsResponse, tags=["Analytics"])
async def stats_endpoint(db: Session = Depends(get_db)) -> StatsResponse:
    """Return actual database counts grouped by script_mix."""
    try:
        return get_stats(db)
    except SQLAlchemyError as exc:
        logger.error(
            "Database error fetching stats",
            extra={"event": "db_error", "extra_data": {"error_type": type(exc).__name__}},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from exc


@router.get("/api/languages", response_model=LanguageInfoResponse, tags=["Metadata"])
async def languages_endpoint() -> LanguageInfoResponse:
    """Return supported language configuration and code-switching guidance."""
    return LanguageInfoResponse(
        supported_languages=[
            {"code": "en", "name": "English", "script": "Latin"},
            {"code": "hi", "name": "Hindi (हिन्दी)", "script": "Devanagari"},
            {
                "code": "hi-en",
                "name": "Mixed Hindi-English (Hinglish)",
                "script": "Devanagari + Latin",
            },
        ],
        detection_mode="automatic (Faster-Whisper language=None, task=transcribe)",
        code_switching_notes=(
            "Whisper detects one dominant language per decoding window. "
            "Mixed Hindi-English speech may output Devanagari, Romanized Hindi, "
            "or mixed script depending on phrase dominance and model size."
        ),
        script_mix_categories=["hindi", "english", "mixed", "other"],
    )
