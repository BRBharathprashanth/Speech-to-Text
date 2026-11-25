"""Pydantic schemas for transcriptions, health, stats, and languages."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ScriptMix = Literal["hindi", "english", "mixed", "other"]


class TranscriptionBase(BaseModel):
    transcription_text: str = Field(..., min_length=1, max_length=100000)
    detected_language: Optional[str] = Field(default=None, max_length=32)
    audio_filename: Optional[str] = Field(default=None, max_length=255)
    audio_format: Optional[str] = Field(default=None, max_length=32)
    audio_duration: Optional[float] = Field(default=None, ge=0.0)
    transcription_status: str = Field(default="completed", max_length=32)

    @field_validator("transcription_text")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("transcription_text must not be empty")
        return cleaned


class TranscriptionCreate(TranscriptionBase):
    session_id: Optional[str] = Field(default=None, max_length=128)


class TranscriptionUpdate(BaseModel):
    transcription_text: Optional[str] = Field(default=None, min_length=1, max_length=100000)
    detected_language: Optional[str] = Field(default=None, max_length=32)
    transcription_status: Optional[str] = Field(default=None, max_length=32)

    @field_validator("transcription_text")
    @classmethod
    def _strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("transcription_text must not be empty")
        return cleaned


class TranscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: Optional[str] = None
    transcription_text: str
    detected_language: Optional[str] = None
    script_mix: str
    audio_filename: Optional[str] = None
    audio_format: Optional[str] = None
    audio_duration: Optional[float] = None
    transcription_status: str
    created_at: datetime
    updated_at: datetime


class TranscriptionListResponse(BaseModel):
    items: list[TranscriptionOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class UploadTranscriptionResponse(BaseModel):
    record: TranscriptionOut
    processing_time_sec: float


class StatsResponse(BaseModel):
    total: int
    hindi: int
    english: int
    mixed: int
    other: int


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    environment: str
    model_name: str
    model_device: str
    model_compute_type: str
    model_status: str
    model_error: Optional[str] = None


class DbHealthResponse(BaseModel):
    status: str
    database: str
    detail: str


class LanguageInfoResponse(BaseModel):
    supported_languages: list[dict[str, str]]
    detection_mode: str
    code_switching_notes: str
    script_mix_categories: list[str]
