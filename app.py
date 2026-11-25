
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
        print(
            f"[diagnostic] migration attempt {attempt}/{max_attempts}",
            flush=True,
        )
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=project_root,
            check=False,
        )
        if result.returncode == 0:
            return
        print(
            f"[diagnostic] migration attempt {attempt} failed "
            f"with exit code {result.returncode}",
            flush=True,
        )
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
        "The full FastAPI dashboard, REST API, and WebSocket streaming UI "
        "are served at `/`.\n\n"
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

# --------------------------------------------------------------
# TEMP: ZeroGPU registration diagnostics (runs after Blocks exits)
# --------------------------------------------------------------
from spaces.zero.decorator import decorated_cache

print("[debug] demo.fns keys:", list(demo.fns.keys()), flush=True)

for key, value in demo.fns.items():
    if isinstance(value, dict) and "fn" in value:
        registered_fn = value["fn"]
        print(
            f"[debug] event={key}, fn={registered_fn}, same_function={registered_fn is _zerogpu_compatibility_check}",
            flush=True,
        )

wrapper = decorated_cache.get(_zerogpu_compatibility_check)

print("[debug] compatibility function id:", id(_zerogpu_compatibility_check), flush=True)
print("[debug] cached wrapper:", wrapper, flush=True)
print(
    "[debug] wrapper zerogpu marker:",
    getattr(wrapper, "zerogpu", "NOT FOUND") if wrapper else "NO WRAPPER",
    flush=True,
)
print("[debug] function in decorated_cache:", _zerogpu_compatibility_check in decorated_cache, flush=True)
print("[debug] demo.fns after mount check:", list(demo.fns.keys()), flush=True)
# END TEMP diagnostics

app = gr.mount_gradio_app(fastapi_app, demo, path="/gradio")

print(
    f"[diagnostic] app.py loaded; __name__={__name__}",
    flush=True,
)


def _report_zerogpu_startup() -> None:
    """Explicitly report registered GPU handlers to Hugging Face ZeroGPU."""
    from spaces.zero import startup

    startup()
    print("[zerogpu] startup report sent", flush=True)


if __name__ == "__main__":
    print("[diagnostic] entered __main__", flush=True)
    print("[diagnostic] invoking ZeroGPU startup", flush=True)
    try:
        _report_zerogpu_startup()
        print("[diagnostic] ZeroGPU startup completed", flush=True)
    except Exception:
        import traceback

        print("[diagnostic] ZeroGPU startup failed", flush=True)
        traceback.print_exc()
        raise
    print("[diagnostic] starting Alembic migrations", flush=True)
    _run_migrations_with_retry()
    print("[diagnostic] Alembic migrations completed", flush=True)
    port = int(os.environ.get("APP_PORT") or "7860")
    print(f"[diagnostic] starting Uvicorn on port {port}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port)
