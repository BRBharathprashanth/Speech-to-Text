FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    WHISPER_MODEL=small \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8

# Install FFmpeg and minimal runtime libs, then clean apt cache.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and model cache directory.
RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser \
    && mkdir -p /app /models/hf /app/logs \
    && chown -R appuser:appuser /app /models/hf

WORKDIR /app

# Install Python dependencies with layer caching.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Pre-download Faster-Whisper small model weights into /models/hf inside image.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" \
    && chown -R appuser:appuser /models/hf

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh

RUN sed -i 's/\r$//' /app/scripts/entrypoint.sh \
    && chmod +x /app/scripts/entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8001

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
