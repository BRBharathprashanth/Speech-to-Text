"""FastAPI application factory, lifespan management, rate limiting, and error handlers."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.api.websocket import router as ws_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.database.connection import init_engine
from app.services.speech_service import get_speech_service

STATIC_DIR = Path(__file__).resolve().parent / "static"


class InMemoryRateLimiter:
    """Simple per-client sliding-window rate limiter for /api/* routes."""

    def __init__(self, max_requests: int, window_sec: int) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_sec
        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            return False
        bucket.append(now)
        return True


def create_app(*, enable_model_warmup: bool = True) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.LOG_DIR)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting Speech to Text application",
            extra={
                "event": "app_startup",
                "extra_data": {
                    "env": settings.APP_ENV,
                    "port": settings.PORT,
                    "model": settings.WHISPER_MODEL,
                },
            },
        )
        init_engine(settings.DATABASE_URL)
        if enable_model_warmup:
            get_speech_service().start_warmup()
        yield
        logger.info("Shutting down Speech to Text application", extra={"event": "app_shutdown"})

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Multilingual Real-Time Speech-to-Text Web Application powered by Faster-Whisper and PostgreSQL",
        lifespan=lifespan,
    )

    rate_limiter = InMemoryRateLimiter(
        max_requests=settings.RATE_LIMIT_REQUESTS,
        window_sec=settings.RATE_LIMIT_WINDOW_SEC,
    )

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            client_ip = request.client.host if request.client else "unknown"
            if not rate_limiter.allow(client_ip):
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Rate limit exceeded. Please slow down requests."},
                )
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled server exception",
            extra={"event": "unhandled_exception", "extra_data": {"error_type": type(exc).__name__}},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred."},
        )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(api_router)
    app.include_router(ws_router)
    return app


app = create_app()
