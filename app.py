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

import spaces
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


@spaces.GPU
def _zerogpu_compatibility_check():
    """Satisfy Hugging Face ZeroGPU startup detection."""
    return None


with gr.Blocks(title="Speech to Text") as demo:
    gr.Markdown(
        "# Speech to Text\n"
        "The full FastAPI dashboard, REST API, and WebSocket streaming UI are served at `/`.\n\n"
        "- Dashboard: `/`\n"
        "- Swagger Docs: `/docs`\n"
        "- Health: `/health` and `/health/db`"
    )
    zerogpu_button = gr.Button(visible=False)
    zerogpu_button.click(
        fn=_zerogpu_compatibility_check,
        inputs=[],
        outputs=[],
    )

app = gr.mount_gradio_app(fastapi_app, demo, path="/gradio")
print(f"[diagnostic] app.py loaded; __name__={__name__}", flush=True)


def _report_zerogpu_startup() -> None:
    """Explicitly report registered GPU handlers to Hugging Face ZeroGPU."""
    from spaces.zero import startup

    startup()
    print("[zerogpu] startup report sent", flush=True)


if __name__ == "__main__":
    print("[diagnostic] entered __main__", flush=True)
    _run_migrations_with_retry()
    _report_zerogpu_startup()
    port = int(os.environ.get("APP_PORT") or "7860")
    uvicorn.run(app, host="0.0.0.0", port=port)

