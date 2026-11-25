"""Hugging Face Spaces (Gradio SDK) entrypoint wrapping the FastAPI + WebSocket app."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure Linux-safe cache and log directories on Hugging Face Spaces.
if not os.environ.get("HF_HOME") or os.environ["HF_HOME"].startswith("D:"):
    os.environ["HF_HOME"] = "/tmp/hf"
if not os.environ.get("LOG_DIR") or os.environ["LOG_DIR"].startswith("D:"):
    os.environ["LOG_DIR"] = "/tmp/logs"
os.makedirs(os.environ["HF_HOME"], exist_ok=True)
os.makedirs(os.environ["LOG_DIR"], exist_ok=True)

import gradio as gr
import uvicorn

from app.main import app as fastapi_app


def _run_migrations_with_retry(max_attempts: int = 10, delay_sec: float = 2.0) -> None:
    """Apply Alembic migrations before starting Uvicorn (handles Neon cold starts)."""
    project_root = str(Path(__file__).resolve().parent)
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=project_root,
            check=False,
        )
        if result.returncode == 0:
            return
        if attempt < max_attempts:
            time.sleep(delay_sec)
    raise RuntimeError(f"Alembic migrations failed after {max_attempts} attempts.")


with gr.Blocks(title="Speech to Text") as demo:
    gr.Markdown(
        "# Speech to Text\n"
        "The full FastAPI dashboard, REST API, and WebSocket streaming UI are served at `/`.\n\n"
        "- Dashboard: `/`\n"
        "- Swagger Docs: `/docs`\n"
        "- Health: `/health` and `/health/db`"
    )

app = gr.mount_gradio_app(fastapi_app, demo, path="/gradio")

if __name__ == "__main__":
    _run_migrations_with_retry()
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
