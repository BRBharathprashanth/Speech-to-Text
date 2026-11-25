#!/bin/sh
set -e

echo "Waiting for database and applying Alembic migrations..."
attempt=1
max_attempts=15
until alembic upgrade head; do
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "Failed to apply Alembic migrations after ${max_attempts} attempts."
    exit 1
  fi
  echo "Database not ready yet (attempt ${attempt}/${max_attempts}); retrying in 2s..."
  attempt=$((attempt + 1))
  sleep 2
done

TARGET_PORT="${PORT:-8001}"
echo "Starting Uvicorn on 0.0.0.0:${TARGET_PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${TARGET_PORT}"
