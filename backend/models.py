"""
models.py
=========
Job metadata lives in Postgres (production) / SQLite (local dev + this
sandbox's tests) via SQLModel. The actual file bytes (input upload,
checkpoint, output) live in object storage (see storage.py) - only the
storage KEYS are stored here, not the data itself, so this table stays
small and fast regardless of how big any individual job's spreadsheet is.

This is the direct replacement for Phase 0's per-job checkpoint CSV +
output xlsx sitting on Streamlit Cloud's ephemeral disk: same idea (one
record per uploaded batch, resumable), but durable and queryable.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, create_engine, Session

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./jarvis_scholar.db")

# Railway/Render Postgres URLs commonly come as "postgres://" - SQLAlchemy
# 1.4+/2.x requires the "postgresql://" scheme instead. Normalize so the
# same DATABASE_URL Railway hands you works without hand-editing it.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)


def new_job_id() -> str:
    return uuid.uuid4().hex[:16]


# Backward-compatible alias used as the table's default_factory.
_new_id = new_job_id


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(SQLModel, table=True):
    id: str = Field(default_factory=_new_id, primary_key=True)

    # Original upload's filename, purely for display - never used as a path.
    filename: str = ""

    # queued -> running -> completed | failed
    status: str = "queued"

    total_rows: int = 0
    done_rows: int = 0
    # Latest human-readable progress message (mirrors Phase 0's
    # progress_callback message argument), for a status-line display.
    progress_message: str = ""

    error_message: str = ""

    # Storage keys (see storage.py) - not local paths, since the API
    # process, the Celery worker, and (on Railway) potentially different
    # container instances all need to reach the same file.
    input_key: str = ""
    checkpoint_key: str = ""
    output_key: str = ""

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class User(SQLModel, table=True):
    """Registered app user. New table -> auto-created by create_all (no
    migration needed, unlike adding a column to an existing table)."""
    id: str = Field(default_factory=_new_id, primary_key=True)
    email: str = Field(index=True)            # unique-by-convention (checked in code)
    name: str = ""
    last_name: str = ""
    institution: str = ""
    role: str = ""                            # Faculty / Student / PhD scholar / Researcher / ...
    designation: str = ""
    password_hash: str = ""                   # pbkdf2$iterations$salt$hash (stdlib, no native deps)
    created_at: datetime = Field(default_factory=_utcnow)
    last_login: datetime = Field(default_factory=_utcnow)


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def get_session_direct() -> Session:
    """Non-generator variant for use inside the Celery task, where FastAPI's
    dependency-injection `yield` pattern doesn't apply."""
    return Session(engine)
