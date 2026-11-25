"""Database engine, session management, and health probe."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def build_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy 2 engine with connection pooling and pre-ping."""
    settings = get_settings()
    url = database_url or settings.DATABASE_URL
    kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
        "future": True,
    }
    if not url.startswith("sqlite"):
        kwargs.update(
            {
                "pool_size": 5,
                "max_overflow": 10,
                "pool_recycle": 1800,
            }
        )
    return create_engine(url, **kwargs)


def init_engine(database_url: str | None = None) -> Engine:
    """Initialize or rebind the module-level engine and sessionmaker."""
    global _engine, _SessionLocal
    _engine = build_engine(database_url)
    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return _engine


def get_engine() -> Engine:
    """Return the active SQLAlchemy engine, initializing lazily if needed."""
    global _engine
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the active sessionmaker."""
    global _SessionLocal
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session and closing it safely."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def check_db_health() -> tuple[bool, str]:
    """Verify database connectivity via SELECT 1 without exposing sensitive details."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except SQLAlchemyError as exc:
        logger.error("Database health check failed", extra={"event": "db_health_error", "extra_data": {"error_type": type(exc).__name__}})
        return False, "Database connection unavailable"
    except Exception as exc:
        logger.error("Unexpected database health check error", extra={"event": "db_health_error", "extra_data": {"error_type": type(exc).__name__}})
        return False, "Database connection unavailable"
