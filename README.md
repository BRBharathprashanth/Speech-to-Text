---
title: Speech to Text
emoji: 🎙️
colorFrom: blue
colorTo: indigo
sdk: gradio
app_file: app.py
pinned: false
---

# Speech-to-Text — Multilingual Real-Time ASR Web Application

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Hugging%20Face%20Spaces-blue?logo=huggingface)](https://bharathprashanth-speech-to-text.hf.space)
[![Swagger Docs](https://img.shields.io/badge/API%20Docs-Swagger%20UI-green?logo=fastapi)](https://bharathprashanth-speech-to-text.hf.space/docs)
[![GitHub](https://img.shields.io/badge/GitHub-BRBharathprashanth-181717?logo=github)](https://github.com/BRBharathprashanth)

A self-hosted, real-time multilingual Speech-to-Text web application built with **Faster-Whisper**, **FastAPI**, **WebSockets**, **AudioWorklet**, **PostgreSQL**, and **Gradio**, deployed on **Hugging Face Spaces**.

It supports live microphone streaming and audio file uploads across **English**, **Hindi (हिन्दी)**, and **Hinglish (mixed Hindi-English)**, with persistent transcription management, search/filtering, and live analytics.

- **Live Application:** https://bharathprashanth-speech-to-text.hf.space
- **Interactive API Docs (Swagger):** https://bharathprashanth-speech-to-text.hf.space/docs
- **GitHub Profile:** https://github.com/BRBharathprashanth

---

## Key Features

- **Real-Time Microphone Streaming (`WS /ws/transcribe`)**: Captures browser audio via `AudioWorklet` (with `ScriptProcessorNode` fallback), downsamples to **16 kHz mono signed 16-bit PCM**, and streams ~200 ms binary frames over WebSockets for near-real-time partial and final transcripts.
- **Rolling Window & Overlap Deduplication**: Decodes rolling audio buffers every ~1.5 s (`beam_size=1`, `vad_filter=True`) and commits segments at ~20 s using word-level boundary overlap merging (`2.0 s` overlap tail) to prevent mid-word splits and duplicate phrases.
- **Audio File Upload Transcription (`POST /api/transcribe`)**: Accepts **WAV, MP3, M4A, FLAC, OGG, and WebM** files (up to `MAX_UPLOAD_MB`, 25 MB default), validates stream integrity with `ffprobe`, normalizes audio to 16 kHz mono WAV via `ffmpeg`, and runs a final transcription pass (`beam_size=3`).
- **Full PostgreSQL CRUD & Analytics Dashboard**: Create, read, search, filter (by script mix and language), paginate, update (recalculating `script_mix` and `updated_at`), and delete transcription records, alongside live database statistics (`GET /api/stats`).
- **Resilient Production Safeguards**: Thread-safe serialized model inference, sliding-window rate limiting on `/api/*`, WebSocket origin validation, concurrent session limits, idempotent `session_id` persistence, structured JSON logging with credential redaction, and Alembic migrations.
- **Responsive Light & Dark UI**: Vanilla HTML/CSS/JS dashboard using safe DOM updates (`textContent`) and automatic WebSocket reconnection with exponential backoff.

---

## Supported Languages

| Language | Code | Script | Handling |
| :--- | :--- | :--- | :--- |
| **English** | `en` | Latin | Automatic detection via Faster-Whisper (`language=None`, `task="transcribe"`) |
| **Hindi (हिन्दी)** | `hi` | Devanagari | Automatic detection with Devanagari script support |
| **Hinglish (Mixed Hindi-English)** | `hi-en` | Devanagari + Latin | Guided with a bilingual initial prompt; deterministic `script_mix` classification (`hindi`, `english`, `mixed`, `other`) computed from saved text |

> **Note on Code-Switching**: Whisper evaluates one dominant language per decoding window. Mixed Hindi-English speech can produce Devanagari, Romanized Hindi, or mixed-script output depending on phrase dominance and model size (`small` vs. `medium`).

---

## Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend & API** | Python 3.11, FastAPI, Uvicorn, Pydantic v2, Pydantic Settings |
| **Speech Recognition** | Faster-Whisper (`ctranslate2` `int8`), FFmpeg / FFprobe |
| **Real-Time Audio** | WebSockets, Web Audio API (`AudioWorklet` 16 kHz mono `pcm_s16le` + `ScriptProcessorNode` fallback) |
| **Database & Migrations** | PostgreSQL 16 (Neon in cloud / Docker locally), SQLAlchemy 2, Alembic (`psycopg2-binary`) |
| **Frontend & Hosting Wrapper** | Vanilla HTML5 / CSS3 / JavaScript, Jinja2 templates, Gradio (`gr.mount_gradio_app` with `ssr_mode=False`) |
| **Deployment & Testing** | Hugging Face Spaces, Docker, Docker Compose, Pytest, FastAPI `TestClient` |

---

## System Architecture

```text
Browser (AudioWorklet / File Upload / Dashboard UI)
   │
   ├── HTTP/REST (/api/transcribe, /api/transcriptions, /api/stats, /health)
   └── WebSocket (WS /ws/transcribe — 16 kHz mono PCM frames)
          │
          ▼
   FastAPI Application (app/main.py)
   ├── Rate Limiter & Origin Validation
   ├── AudioService (ffprobe validation + ffmpeg 16 kHz mono WAV normalization)
   ├── StreamingService (rolling buffer + word-level overlap deduplication)
   ├── SpeechService (singleton Faster-Whisper with serialized inference lock)
   └── TranscriptionService (CRUD, stats, deterministic script_mix classifier)
          │
          ▼
   PostgreSQL 16 (SQLAlchemy 2 + Alembic migrations)

   Mounted inside Hugging Face Spaces entrypoint (app.py):
   FastAPI app + Gradio Blocks mounted at /gradio (ssr_mode=False)
```

### Project Structure

```text
Speech-to-Text/
├── app.py                           # Hugging Face Spaces entrypoint (FastAPI + Gradio mount + migrations)
├── app/
│   ├── main.py                      # FastAPI app factory, lifespan, rate limiter, error handlers
│   ├── api/
│   │   ├── routes.py                # REST endpoints (/, /health, /api/transcribe, CRUD, stats, languages)
│   │   └── websocket.py             # WS /ws/transcribe with origin & session limit enforcement
│   ├── core/
│   │   ├── config.py                # Typed Pydantic Settings & postgres:// URL normalization
│   │   └── logging.py               # Structured JSON logging with credential redaction
│   ├── database/
│   │   ├── connection.py            # SQLAlchemy 2 engine (pool_pre_ping=True) & sessions
│   │   ├── models.py                # Transcription ORM model & indexes
│   │   └── migrations/              # Alembic migration scripts
│   ├── schemas/
│   │   └── transcription.py         # Pydantic request/response schemas
│   ├── services/
│   │   ├── speech_service.py        # Faster-Whisper singleton, warm-up, serialized inference
│   │   ├── audio_service.py         # Upload validation, sanitization, FFmpeg 16 kHz mono WAV
│   │   ├── transcription_service.py # CRUD, stats, Devanagari/Latin script_mix classifier
│   │   └── streaming_service.py     # Rolling buffer, overlap deduplication, final pass
│   ├── templates/index.html         # Dashboard HTML template
│   └── static/
│       ├── css/style.css            # Light/dark theme styles
│       └── js/
│           ├── app.js               # Dashboard logic, WS reconnect, XHR upload progress
│           └── pcm-worklet.js       # AudioWorklet 16 kHz mono int16 PCM resampler
├── deploy/huggingface/README.md     # Alternate Docker SDK Space configuration reference
├── scripts/entrypoint.sh            # Container DB wait + Alembic upgrade + Uvicorn startup
├── tests/                           # Unit, DB, CRUD, WebSocket, and slow real-audio tests
├── Dockerfile                       # Non-root python:3.11-slim + FFmpeg + pre-cached small model
├── docker-compose.yml               # PostgreSQL 16 + FastAPI web service
├── alembic.ini
├── requirements.txt
└── requirements-dev.txt
```

---

## Installation & Local Setup

### Prerequisites
- **Python 3.11**
- **PostgreSQL 16** (local installation or via Docker)
- **FFmpeg / FFprobe** installed and available on `PATH`
- *(Optional)* **Docker & Docker Compose** for containerized setup

### 1. Clone & Configure Environment

```powershell
git clone https://github.com/BRBharathprashanth/Speech-to-Text.git
cd Speech-to-Text
Copy-Item .env.example .env
```

Update `.env` with your PostgreSQL `DATABASE_URL` and local `HF_HOME` cache path if needed.

### 2. Native Setup (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

- **Web Dashboard:** `http://localhost:8001`
- **Swagger API Docs:** `http://localhost:8001/docs`

> **Tip:** If you do not have a local PostgreSQL 16 server running, you can start only the database container with `docker compose up -d db` before running `alembic upgrade head`.

### 3. Optional: Docker Compose

```powershell
docker compose up -d --build
```

- **Web Dashboard:** `http://localhost:8001`
- **Swagger API Docs:** `http://localhost:8001/docs`
- **PostgreSQL 16:** bound to `127.0.0.1:5432` with persistent volume `speech_to_text_postgres_data`

### Running Tests

```powershell
# Fast suite (stubbed Whisper model, isolated SQLite test DB by default)
pytest -m "not slow" -v

# Slow real-audio tests (requires en.wav, hi.wav, hinglish.wav in tests/audio/)
pytest -m slow -v -s
```

---

## API Documentation

Interactive OpenAPI / Swagger documentation is served automatically by FastAPI:
- **Live Space:** https://bharathprashanth-speech-to-text.hf.space/docs
- **Local:** `http://localhost:8001/docs`

| Method | Endpoint | Purpose |
| :--- | :--- | :--- |
| `GET` | `/` | Frontend Speech-to-Text dashboard |
| `GET` | `/health` | Application & Faster-Whisper model status |
| `GET` | `/health/db` | PostgreSQL connectivity check (`SELECT 1`) |
| `POST` | `/api/transcribe` | Upload audio file, convert via FFmpeg, transcribe, persist |
| `POST` | `/api/transcriptions` | Create/save transcription (idempotent on `session_id`) |
| `GET` | `/api/transcriptions` | Paginated search & filter (`q`, `script_mix`, `language`, `page`, `page_size`) |
| `GET` | `/api/transcriptions/{id}` | Retrieve a single transcription by ID |
| `PUT` | `/api/transcriptions/{id}` | Update transcription text (recalculates `script_mix` & `updated_at`) |
| `DELETE` | `/api/transcriptions/{id}` | Delete a transcription by ID |
| `GET` | `/api/stats` | Live counts grouped by `script_mix` (`total`, `hindi`, `english`, `mixed`, `other`) |
| `GET` | `/api/languages` | Supported languages & code-switching metadata |
| `WS` | `/ws/transcribe` | Real-time 16 kHz mono PCM audio streaming |

---

## Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `APP_NAME` | `Speech to Text` | Application title |
| `APP_VERSION` | `1.0.0` | Application version |
| `APP_ENV` | `development` | Environment (`development` / `production`) |
| `PORT` | `8001` | HTTP/WebSocket server port (local/Docker) |
| `APP_PORT` | `7860` | Server port used by `app.py` on Hugging Face Spaces |
| `DATABASE_URL` | `postgresql://stt_user:stt_password@localhost:5432/speech_to_text_db` | PostgreSQL URL (`postgres://` auto-normalized to `postgresql://`) |
| `WHISPER_MODEL` | `small` | Faster-Whisper model size (`small` / `medium`) |
| `WHISPER_DEVICE` | `cpu` | Inference device (`cpu`) |
| `WHISPER_COMPUTE_TYPE` | `int8` | CTranslate2 compute precision (`int8`) |
| `HF_HOME` | `D:\AI-Models\huggingface` | Hugging Face model cache directory (`/tmp/hf` on HF Spaces, `/models/hf` in Docker) |
| `MAX_UPLOAD_MB` | `25` | Maximum audio upload size in MB (1–200) |
| `MAX_SESSION_SECONDS` | `600` | Maximum live WebSocket recording duration in seconds |
| `MAX_CONCURRENT_SESSIONS` | `3` | Maximum simultaneous active WebSocket sessions |
| `FINAL_FULL_PASS_MAX_SEC` | `60` | Max duration (s) for full-audio final pass before tail-stitching |
| `MAX_WS_FRAME_BYTES` | `65536` | Maximum binary WebSocket audio frame size in bytes |
| `ALLOWED_WS_ORIGINS` | `""` | Comma-separated allowed WebSocket `Origin` URLs (empty = match request `Host`) |
| `LOG_DIR` | `./logs` | Directory for structured JSON logs |
| `RATE_LIMIT_REQUESTS` | `120` | Max `/api/*` requests per client IP per window |
| `RATE_LIMIT_WINDOW_SEC` | `60` | Rate-limiter sliding window in seconds |

---

## Deployment Details

The live application is hosted on **Hugging Face Spaces** (`https://bharathprashanth-speech-to-text.hf.space`) paired with **Neon** managed PostgreSQL:

- **Entrypoint (`app.py`)**: Wraps the FastAPI + WebSocket app (`app.main:app`) with Gradio (`gr.mount_gradio_app(fastapi_app, demo, path="/gradio", ssr_mode=False)`), runs Alembic migrations with retry logic for database cold starts, and serves via Uvicorn on port `7860` (`APP_PORT`).
- **System Dependencies (`packages.txt`)**: Installs `ffmpeg` and `libgomp1` for audio decoding and Faster-Whisper/CTranslate2 execution.
- **Memory & Cold-Start Notes**: Faster-Whisper `small` (`int8`) uses ~1.5–2.0 GB RAM under active inference, fitting within Hugging Face Spaces' 16 GB RAM tier. Free Spaces sleep after inactivity, which drops active WebSocket connections and introduces a cold-start delay on the next request.
- **Docker Alternative**: A production `Dockerfile` (baking `small` model weights into `/models/hf`) and `deploy/huggingface/README.md` are also included for `sdk: docker` deployments.

---

## Future Improvements

- **Speaker Diarization & Timestamps**: Add per-speaker segmentation and word-level timestamps in exported transcripts.
- **Export Formats**: Support downloading transcriptions as `.txt`, `.srt`, `.vtt`, and `.json`.
- **Hinglish Post-Processing**: Optional script normalization or transliteration toggle between Devanagari and Romanized Hindi.
- **GPU Acceleration & Larger Models**: Enable CUDA/ZeroGPU inference profiles for `medium` or `large-v3` models to improve accuracy on noisy audio and heavy code-switching.
- **Authentication & Multi-User Workspaces**: Add user accounts so personal transcription histories can be isolated across sessions.
