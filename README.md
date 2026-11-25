# Speech to Text — Multilingual Real-Time ASR Web Application

A self-hosted, real-time multilingual Speech-to-Text web application supporting **English**, **Hindi (हिन्दी)**, and **mixed Hindi-English (Hinglish)** speech using **Faster-Whisper**, **FastAPI**, **WebSockets**, **AudioWorklet (16 kHz mono PCM)**, and **PostgreSQL 16**.

## Assessment Requirements & Privacy Guarantees
- **100% Self-Hosted Recognition**: Uses open-source Faster-Whisper (`small` / `medium`, CPU `int8`). User audio never leaves the server for transcription.
- **Real-Time Streaming**: Captures microphone audio via `AudioWorklet` (with `ScriptProcessorNode` fallback), downsamples to 16 kHz mono signed 16-bit PCM, and streams binary frames over `WS /ws/transcribe`.
- **File Upload Transcription**: `POST /api/transcribe` accepts WAV, MP3, M4A, FLAC, OGG, and WebM up to `MAX_UPLOAD_MB` (25 MB default), validates stream integrity with `ffprobe`, normalizes via `ffmpeg`, and persists results.
- **Complete PostgreSQL CRUD Dashboard**: Create, Read, Search/Filter/Paginate, Update (re-evaluating `script_mix` and `updated_at`), Delete with confirmation, and live DB statistics.
- **Light & Dark Themes**: Responsive SaaS-style vanilla HTML/CSS/JS UI using safe DOM rendering (`textContent`, no untrusted `innerHTML`).

## Technology Stack
- **Backend**: Python 3.11, FastAPI, Uvicorn, Pydantic v2, Pydantic Settings
- **Speech Recognition**: Faster-Whisper (`ctranslate2` int8), FFmpeg / FFprobe
- **Database**: PostgreSQL 16, SQLAlchemy 2, Alembic (`psycopg2-binary`)
- **Frontend**: HTML5, CSS3, Vanilla JavaScript, Web Audio API (`AudioWorklet`), WebSockets
- **Infrastructure & Testing**: Docker, Docker Compose, Pytest, FastAPI `TestClient`

## Project Structure
```text
Speech-to-Text/
├── app/
│   ├── main.py                      # FastAPI app factory, lifespan, rate limiter
│   ├── api/
│   │   ├── routes.py                # HTTP endpoints (/health, /api/transcribe, CRUD, stats)
│   │   └── websocket.py             # WS /ws/transcribe with origin & limit enforcement
│   ├── core/
│   │   ├── config.py                # Typed Pydantic Settings & postgres:// normalization
│   │   └── logging.py               # Structured JSON logging with credential redaction
│   ├── database/
│   │   ├── connection.py            # SQLAlchemy 2 engine (pool_pre_ping=True) & sessions
│   │   ├── models.py                # Transcription ORM table & indexes
│   │   └── migrations/              # Alembic migrations
│   ├── schemas/
│   │   └── transcription.py         # Request/response Pydantic models
│   ├── services/
│   │   ├── speech_service.py        # Faster-Whisper singleton, warm-up, serialized inference
│   │   ├── audio_service.py         # Upload validation, sanitization, FFmpeg 16kHz mono WAV
│   │   ├── transcription_service.py # CRUD, stats, Devanagari/Latin script_mix classifier
│   │   └── streaming_service.py     # Rolling buffer, overlap deduplication, final pass
│   ├── templates/index.html         # Dashboard HTML
│   └── static/
│       ├── css/style.css            # Light/dark theme styles
│       └── js/
│           ├── app.js               # Dashboard logic, WS reconnect, XHR upload progress
│           └── pcm-worklet.js       # AudioWorklet 16 kHz mono int16 PCM resampler
├── tests/                           # Fast unit/DB/CRUD/WS tests & slow real-audio tests
├── scripts/entrypoint.sh            # Container DB wait + Alembic upgrade + Uvicorn startup
├── Dockerfile                       # Non-root python:3.11-slim + FFmpeg + baked small model
├── docker-compose.yml               # PostgreSQL 16 (named volume) + FastAPI web service
├── alembic.ini
├── requirements.txt
└── requirements-dev.txt
```

## Near-Real-Time Audio Architecture
1. **Browser Capture (`pcm-worklet.js`)**: Captures microphone input at the device sample rate, mixes down to mono, linearly resamples to **16,000 Hz**, quantizes to **signed 16-bit PCM (`pcm_s16le`)**, and emits ~200 ms frames (6,400 bytes). Falls back to `ScriptProcessorNode` if `AudioWorklet` is unavailable.
2. **Session Handshake**: Client generates a UUID `session_id` and sends `{"type": "start", "session_id": "...", "sample_rate": 16000, "channels": 1}` over `WS /ws/transcribe`.
3. **Rolling Window & Overlap Deduplication**:
   - Server buffers PCM in memory and decodes partial hypotheses every ~1.5 s (`beam_size=1`, `vad_filter=True`, `condition_on_previous_text=False`, `language=None`).
   - Committed text and temporary partial text are kept separate so each partial update replaces only the temporary span.
   - At ~20 s, segments are committed via word-level boundary overlap merging, retaining a 2.0 s overlap tail in the rolling buffer to avoid mid-word splits.
4. **Final Pass**:
   - Recordings `<= FINAL_FULL_PASS_MAX_SEC` (60 s) run a full-audio final pass (`beam_size=3`).
   - Longer recordings drop the full raw buffer after 60 s to bound memory and stitch the final unprocessed tail onto committed segments.
   - Saved once in PostgreSQL using a unique constraint on `session_id` for idempotency.
5. **Reconnection Limitation**: Rolling buffers reside in server RAM during an active session. If a connection drops briefly (`<= 30 s`), the client reconnects with exponential backoff and resumes the same `session_id`. If the server restarts or the session expires, missing audio cannot be recovered and the UI informs the user to restart recording.

## Model Caching & Memory Notes
- **Native Windows (example path)**: `HF_HOME=D:\AI-Models\huggingface` (example local Windows path; set to any writable directory on your machine).
- **Docker Container**: Only the Faster-Whisper `small` (`int8`) model weights are baked into `/models/hf` during `docker build`, with `HF_HOME=/models/hf` at runtime. Never bind-mount an empty host directory over `/models/hf`. If you switch `WHISPER_MODEL=medium`, it will download at first container startup.
- **Memory**: Faster-Whisper `small` (`int8` on CPU) typically uses **~1.5–2.0 GB RAM** under active inference. Do not deploy on 512 MB RAM instances.
- **Model Switching**: Change `WHISPER_MODEL=small` or `WHISPER_MODEL=medium` via environment variables only.
- **Stop-Recording Timeout**: On the frontend, clicking **Stop Recording** starts a **15-second fallback timeout** (`scheduleFinalTimeout(15000)` in `app/static/js/app.js`). If the server's `final` WebSocket message arrives first, the timer is cleared; if it does not arrive within 15 seconds, the UI stops local capture and displays a timeout notification.

## Environment Variables
| Variable | Default | Description |
| :--- | :--- | :--- |
| `APP_NAME` | `Speech to Text` | Application title |
| `APP_VERSION` | `1.0.0` | Application version |
| `APP_ENV` | `development` | Environment (`development` / `production`) |
| `PORT` | `8001` | HTTP/WebSocket server port |
| `DATABASE_URL` | `postgresql://stt_user:stt_password@localhost:5432/speech_to_text_db` | PostgreSQL connection string (`postgres://` auto-normalized to `postgresql://`) |
| `WHISPER_MODEL` | `small` | Faster-Whisper model size (`small` baked in Docker; `medium` downloads on first start) |
| `WHISPER_DEVICE` | `cpu` | Inference device (`cpu`) |
| `WHISPER_COMPUTE_TYPE` | `int8` | CTranslate2 compute precision (`int8`) |
| `HF_HOME` | `D:\AI-Models\huggingface` | Hugging Face model cache directory (`/models/hf` in Docker) |
| `MAX_UPLOAD_MB` | `25` | Maximum audio upload size in MB (1–200) |
| `MAX_SESSION_SECONDS` | `600` | Maximum live WebSocket recording duration in seconds |
| `MAX_CONCURRENT_SESSIONS` | `3` | Maximum simultaneous active WebSocket sessions |
| `FINAL_FULL_PASS_MAX_SEC` | `60` | Max duration (s) for full-audio final pass before tail-stitching |
| `MAX_WS_FRAME_BYTES` | `65536` | Maximum binary WebSocket audio frame size in bytes |
| `ALLOWED_WS_ORIGINS` | `""` | Comma-separated allowed WebSocket `Origin` URLs (empty = match request `Host`) |
| `LOG_DIR` | `./logs` | Directory for structured JSON logs |
| `RATE_LIMIT_REQUESTS` | `120` | Max `/api/*` requests per client IP per window |
| `RATE_LIMIT_WINDOW_SEC` | `60` | Rate-limiter sliding window in seconds |

## Setup & Running

### 1. Environment Configuration
Copy `.env.example` to `.env` and fill in your PostgreSQL credentials:
```powershell
Copy-Item .env.example .env
```

### 2. Docker Compose (Recommended)
```powershell
docker compose up -d --build
```
- Web dashboard: `http://localhost:8001`
- Swagger API docs: `http://localhost:8001/docs`
- PostgreSQL 16 runs on `127.0.0.1:5432` (never publicly exposed) using persistent volume `speech_to_text_postgres_data`.

### 3. Native Windows Development
```powershell
py -3.11 -m venv D:\Projects\Speech-to-Text\.venv
D:\Projects\Speech-to-Text\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

## API Endpoints
| Method | Endpoint | Purpose |
| :--- | :--- | :--- |
| `GET` | `/` | Frontend dashboard |
| `GET` | `/health` | Application & Faster-Whisper model status |
| `GET` | `/health/db` | PostgreSQL connectivity check (`SELECT 1`) |
| `POST` | `/api/transcribe` | Upload audio file, convert via FFmpeg, transcribe, save |
| `POST` | `/api/transcriptions` | Create/save transcription (idempotent on `session_id`) |
| `GET` | `/api/transcriptions` | Paginated search (`q`, `script_mix`, `language`, `page`, `page_size`) |
| `GET` | `/api/transcriptions/{id}` | Get transcription by ID |
| `PUT` | `/api/transcriptions/{id}` | Update transcription text (updates `script_mix` & `updated_at`) |
| `DELETE` | `/api/transcriptions/{id}` | Delete transcription by ID |
| `GET` | `/api/stats` | Live counts (`total`, `hindi`, `english`, `mixed`, `other`) |
| `GET` | `/api/languages` | Supported languages & code-switching metadata |
| `WS` | `/ws/transcribe` | Real-time 16 kHz mono PCM streaming |

## Hindi-English Code-Switching & Limitations
- Whisper evaluates one dominant language per decoding window (`language=None`, `task="transcribe"`), guided by an initial Hinglish prompt: `"Hindi and English mixed. नमस्ते, hello, मैं ठीक हूँ, thank you."`
- Mixed Hindi-English speech can produce all-Devanagari, all-Romanized, or mixed-script output depending on phrase dominance and model size (`small` vs `medium`).
- `script_mix` is computed deterministically from Devanagari vs. Latin letter ratios in the actual saved transcript rather than trusting Whisper's single language tag alone.

## Testing
```powershell
# Fast suite (stubbed Whisper model, real PostgreSQL or SQLite test DB)
pytest -m "not slow" -v

# Slow real-audio tests (requires en.wav, hi.wav, hinglish.wav in tests/audio/)
pytest -m slow -v -s
```

### Real-Audio Accuracy Tests (`tests/audio/`)
Place real 16 kHz (or standard PCM) `.wav` recordings in `tests/audio/`:
- `tests/audio/en.wav` — English speech sample
- `tests/audio/hi.wav` — Hindi speech sample
- `tests/audio/hinglish.wav` — Mixed Hindi-English speech sample

### Measured Results (`small` vs `medium`)
| Sample | Model | Detected Lang | `script_mix` | Latency (s) | WER / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `en.wav` | `small` | `[FILL: lang]` | `[FILL: mix]` | `[FILL: sec]` | `[FILL: transcript / WER notes]` |
| `hi.wav` | `small` | `[FILL: lang]` | `[FILL: mix]` | `[FILL: sec]` | `[FILL: transcript / WER notes]` |
| `hinglish.wav` | `small` | `[FILL: lang]` | `[FILL: mix]` | `[FILL: sec]` | `[FILL: transcript / WER notes]` |
| `hinglish.wav` | `medium` | `[FILL: lang]` | `[FILL: mix]` | `[FILL: sec]` | `[FILL: transcript / WER notes]` |

### Browser Microphone Manual Verification (Chrome / Edge)
1. Open `http://localhost:8001` (or your HTTPS cloud URL) in Chrome or Edge.
2. Confirm the header shows `App OK • Model (small): ready` and `DB: Connected`.
3. Click **Start Recording** and grant microphone permission when prompted.
4. Speak a sentence; verify `WS: Connected`, live partial updates appear, and the timer increments.
5. Click **Stop Recording**; verify the final transcript appears, saves to PostgreSQL, and shows up in **Transcription History** and **Statistics**.

## Cloud Deployment (Hugging Face Spaces + Neon PostgreSQL)
- **Resource Fit**: Faster-Whisper `small` (`int8`) uses ~1.5–2.0 GB RAM under active inference. Hugging Face Spaces **CPU Basic (Free, 16 GB RAM, 2 vCPU)** meets this requirement without paid tiers (unlike 512 MB tiers).
- **Database**: Pair with a free-tier managed PostgreSQL provider such as **Neon** (`sslmode=require`), configured via the `DATABASE_URL` Space Secret.
- **Privacy Qualifier**: When deployed on Hugging Face Spaces, audio is processed on Hugging Face's container infrastructure (not your local machine); only the resulting transcript text and metadata are stored in Neon PostgreSQL.
- **Configuration**: See `deploy/huggingface/README.md` for the required Space YAML frontmatter (`sdk: docker`, `app_port: 8001`) and environment variables.
- **Known Free-Tier Limitation**: Free Hugging Face Spaces sleep after inactivity, which drops active WebSocket connections and causes a cold-start delay on the next request.

## Troubleshooting
- **Model still loading on startup**: Wait a few seconds and refresh `/health` until `model_status` transitions from `loading` to `ready`.
- **Microphone button fails**: Browsers require `https://` or `http://localhost` for `navigator.mediaDevices.getUserMedia`.
- **Database connection refused**: Ensure `docker compose up -d db` is running and `DATABASE_URL` matches `.env`.

