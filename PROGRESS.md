# Project Progress — Speech to Text

## Phase 0 — Environment Inspection ✅
- D: drive: 22 GB free / 160 GB total
- Python 3.11.9, pip 26.3, Git 2.55.0, FFmpeg 9.0, Docker 29.9.3, Docker Compose v5.7.0
- Ports 8001 and 5432 were free
- Created project skeleton + `.venv` on D:\Projects\Speech-to-Text

## Phase 1 — Walking Skeleton ✅
- FastAPI application factory with lifespan, rate limiter, structured logging
- PostgreSQL 16 via Docker Compose with persistent named volume
- SQLAlchemy 2 ORM with `Transcription` table, 3 indexes
- Alembic migration `0001_create_transcriptions` applied successfully
- Faster-Whisper `small` (cpu, int8) with background warm-up, serialized CPU inference
- `POST /api/transcribe` upload: validate → ffprobe → ffmpeg 16kHz mono → Whisper → save to DB
- Tested: sine wave upload → 422 (no speech detected) confirms full pipeline execution

## Phase 2 — Real-Time Pipeline ✅
- AudioWorklet (`pcm-worklet.js`) with ScriptProcessorNode fallback
- 16 kHz mono signed 16-bit PCM resampling via linear interpolation
- WebSocket `/ws/transcribe` with origin validation, session handshake, limit enforcement
- Rolling audio buffer with ~1.5s partial decode, ~20s segment commits
- Word-level overlap deduplication across committed/partial text boundaries
- Final full-audio pass for short sessions (≤60s, beam_size=3), tail-stitch for longer ones
- Idempotent save via unique session_id constraint
- Exponential backoff reconnection with 30s session resume TTL
- Max session duration, max concurrent sessions, max frame size enforcement
- Tested: 6/6 WebSocket pytest tests passing

## Phase 3 — CRUD and Dashboard ✅
- Complete CRUD API: Create, Read (paginated with search/filter), Update, Delete
- `/api/stats` returns actual DB counts (total, hindi, english, mixed, other)
- `/api/languages` metadata endpoint
- Responsive SaaS dashboard with light/dark themes
- Recording panel: start/stop/clear/save, timer, mic permission, WS status, live lang badges
- Upload panel: drag-and-drop, progress bar, format validation, result display
- History table: ID, preview, language, script_mix badge, duration, timestamps, actions
- View/Edit modal with save/cancel/copy, Delete confirmation modal
- Toast notifications, loading/empty/error states
- Safe DOM rendering (textContent only, no innerHTML with untrusted content)

## Phase 4 — Docker ✅
- `python:3.11-slim` Dockerfile with FFmpeg, non-root user, baked Faster-Whisper small model
- Docker image: `speech-to-text-web:latest` (2.44 GB including model weights at /models/hf)
- `docker-compose.yml`: PostgreSQL 16 (healthcheck, persistent volume) + FastAPI web service
- `scripts/entrypoint.sh`: DB wait loop + Alembic upgrade + Uvicorn with dynamic PORT
- Build verified, both containers running and healthy
- Restart persistence verified: record survived `docker compose restart`
- CRUD tested against live Docker stack: create → restart → read (persisted) → update → delete

## Phase 5 — Testing ✅
### Fast Tests (23 passed, 0 failed, 6 deselected):
- test_audio.py: 6 passed (valid upload, reject invalid ext/empty/corrupt/bad MIME/oversize)
- test_crud.py: 1 passed (full CRUD + stats flow with script_mix verification)
- test_database.py: 2 passed (idempotent session_id + updated_at advances on edit)
- test_health.py: 4 passed (app health, DB health, languages, dashboard HTML)
- test_unit.py: 4 passed (URL normalization, script_mix classification, overlap dedup, filename sanitize)
- test_websocket.py: 6 passed (stream+final save, origin reject, oversize frame, max duration, max concurrent, resume/session_lost)

### Slow Tests (6 deselected — awaiting real recordings):
- test_transcription_slow.py: requires en.wav, hi.wav, hinglish.wav in tests/audio/
- Tests parametrized across small and medium model sizes

### Manual Browser Microphone Test:
- **NOT YET PERFORMED** — requires user to open http://localhost:8001 in Chrome/Edge

## Phase 6 & 7 — Cloud Deployment ⏳
- **Platform selected**: Hugging Face Spaces (Docker, free CPU Basic tier, 16 GB RAM)
- **External DB needed**: Neon or Supabase free PostgreSQL
- **Limitation**: Spaces sleep on inactivity (WebSocket connections will drop when idle)
- **Status**: Deployment configuration prepared, requires HF account authentication

## Phase 8 — GitHub ⏳
- Local Git repo initialized on `main` branch
- Commit `f2bc74b`: 43 files, 5585 insertions
- `.env` excluded, secrets scan clean, no model files or audio recordings staged
- **Blocked**: GitHub repository needs to be created (gh CLI not installed)
- Remote set to `https://github.com/BRBharathprashanth/Speech-to-Text.git`
- **Action needed**: Create repo on GitHub and authenticate for push

## Known Issues
- `gh` CLI not installed — git push requires manual repo creation or gh installation
- Real-time microphone not yet browser-tested
- Hindi/English/Hinglish accuracy tests pending real recordings
- Cloud deployment pending authentication
- Docker Compose default passwords in env var substitutions are development-only defaults
