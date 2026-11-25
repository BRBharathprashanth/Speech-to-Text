# Project Progress — Speech to Text

Status legend: **Done** | **Tested** | **Partial** | **Pending**

## Phase 0 — Environment Inspection — Done
- D: drive: 22 GB free / 160 GB total
- Python 3.11.9, pip 26.3, Git 2.55.0, FFmpeg 9.0, Docker 29.9.3, Docker Compose v5.7.0, Node.js v26.13.1
- Created project skeleton + `.venv` on `D:\Projects\Speech-to-Text`

## Phase 1 — Walking Skeleton — Done & Tested
- FastAPI application factory with lifespan, rate limiter, structured logging (`app/main.py`)
- PostgreSQL 16 via Docker Compose with persistent named volume (`speech_to_text_postgres_data`)
- SQLAlchemy 2 ORM with `Transcription` table, 3 indexes, unique `session_id` (`app/database/models.py`)
- Alembic migration `0001_create_transcriptions` applied (`alembic current` verified)
- Faster-Whisper `small` (cpu, int8) with background warm-up, serialized CPU inference

## Phase 2 — Real-Time Pipeline — Done & Tested
- AudioWorklet (`pcm-worklet.js`) with `ScriptProcessorNode` fallback, 16 kHz mono signed 16-bit PCM
- WebSocket `/ws/transcribe` with origin validation, session handshake, limit enforcement
- Rolling audio buffer with ~1.5 s partial decode, ~20 s segment commits, word-level overlap deduplication
- Final full-audio pass (`<= 60s`, `beam_size=3`), tail-stitch for longer sessions, idempotent `session_id` save
- Frontend stop-recording finalization timeout (15 s fallback in `app/static/js/app.js`, commit `64b413f`)
- Verified: `node --check app/static/js/app.js` clean, 6/6 WebSocket pytest tests passing, manual English browser mic test passed

## Phase 3 — CRUD and Dashboard — Done & Tested
- Complete CRUD API + `/api/stats` + `/api/languages`
- Responsive dashboard with light/dark themes, recording panel, upload panel, history table, view/edit/delete modals, safe DOM rendering (`textContent`)

## Phase 4 — Docker — Done & Tested
- `python:3.11-slim` Dockerfile with FFmpeg, non-root `appuser`, baked Faster-Whisper `small` model at `/models/hf`
- `docker compose build` & `docker compose up -d` verified: `speech_to_text_db` healthy, `speech_to_text_web` up on port 8001
- `/health` (`model_status: ready`) and `/health/db` (`database: connected`) verified
- Startup Alembic migration (`0001_create_transcriptions (head)`) and `HF_HOME=/models/hf` verified in container
- Persistence verified across `docker compose restart` (record #14 created, persisted across restart, then deleted)

## Phase 5 — Testing — Partial
- **Fast suite (`pytest -q -m "not slow"`) — Tested:** `23 passed, 6 deselected in 0.78s`
- **Slow real-audio tests (`pytest -m slow`) — Pending:** awaiting user recordings `en.wav`, `hi.wav`, `hinglish.wav` in `tests/audio/`
- **Manual browser microphone check (English) — Tested:** Start, speak, Stop worked with final transcript saved once and no timeout toast/console errors; Hindi/Hinglish live test pending

## Phase 6 & 7 — Cloud Deployment — Partial (Prep Done, Deploy Pending)
- **Platform:** Hugging Face Spaces (Docker, CPU Basic Free: 2 vCPU, 16 GB RAM, 50 GB ephemeral disk) + Neon PostgreSQL Free Tier (1 GB storage, 100 CU-hours/month, scale-to-zero after 5 min)
- **Config:** `deploy/huggingface/README.md` prepared (`sdk: docker`, `app_port: 8001`, env vars/secrets documented)
- **Pending:** User approval and Hugging Face / Neon account login

## Phase 8 — GitHub — Partial (Prep Done, Push Pending)
- Local Git repo on `main` branch (`HEAD` = `64b413f`)
- Secrets scan clean: `.env` gitignored, `.env.example` has placeholders only, `*.backup` and `*.corrupted-*` gitignored
- **Pending:** GitHub repository creation / `gh auth login` and `git push`
