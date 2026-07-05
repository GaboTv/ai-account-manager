"""SQLModel models mirroring db/001_init.sql. No provider tokens, ever."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Session, SQLModel, create_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://aimgr:aimgr@localhost:5432/aimgr"
)
engine = create_engine(DATABASE_URL)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIAccount(SQLModel, table=True):
    __tablename__ = "ai_accounts"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider: str
    name: str = Field(unique=True, index=True)
    container_name: str = Field(unique=True)
    image: str
    auth_volume: str
    workspace_volume: str
    cpu_limit: float = 1
    memory_limit_mb: int = 1024
    status: str = "created"
    auth_status: str = "unknown"
    # parsed provider metadata (email, plan, auth method) — never tokens
    auth_info: dict = Field(
        default_factory=dict,
        sa_column=Column("auth_info", JSONB, nullable=False, server_default=text("'{}'")),
    )
    # parsed /usage (claude) or /status (codex) output: limits, resets, plan
    usage_info: dict = Field(
        default_factory=dict,
        sa_column=Column("usage_info", JSONB, nullable=False, server_default=text("'{}'")),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UsageSnapshot(SQLModel, table=True):
    """Point-in-time copy of an account's parsed limits, taken on every
    usage capture (manual or scheduled). Feeds the daily-usage dashboard."""
    __tablename__ = "usage_snapshots"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="ai_accounts.id", index=True)
    taken_at: datetime = Field(default_factory=utcnow, index=True)
    limits: list = Field(
        default_factory=list,
        sa_column=Column("limits", JSONB, nullable=False, server_default=text("'[]'")),
    )


class AISession(SQLModel, table=True):
    __tablename__ = "ai_sessions"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="ai_accounts.id")
    provider: str
    mode: str
    pty_process_id: str | None = None
    status: str = "active"
    created_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None


class AICommandRun(SQLModel, table=True):
    __tablename__ = "ai_command_runs"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID | None = Field(default=None, foreign_key="ai_sessions.id")
    account_id: uuid.UUID = Field(foreign_key="ai_accounts.id")
    command: str
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_id: str = "local-user"
    account_id: uuid.UUID | None = Field(default=None, foreign_key="ai_accounts.id")
    event_type: str
    metadata_json: dict = Field(
        default_factory=dict, sa_column=Column("metadata", JSONB, nullable=False)
    )
    created_at: datetime = Field(default_factory=utcnow)


def get_session():
    # expire_on_commit=False: a later commit (e.g. audit()) must not expire
    # attributes on an object we still intend to return/serialize — otherwise
    # FastAPI serializes it as {}.
    with Session(engine, expire_on_commit=False) as session:
        yield session


def audit(db: Session, event_type: str, account_id=None, metadata: dict | None = None):
    import json
    from .redact import redact

    db.add(
        AuditEvent(
            event_type=event_type,
            account_id=account_id,
            metadata_json=json.loads(redact(json.dumps(metadata or {}))),
        )
    )
    db.commit()
