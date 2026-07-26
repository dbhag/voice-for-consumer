"""SQLAlchemy ORM tables mirroring the engine's Pydantic domain models.

Wired up in `app/db/repository.py`, used by the arq worker (`app/queue/tasks.py`)
to persist results and by the API (`app/api/routes/jobs.py`) to read them back.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    # "queued" | "running" | "done" | "failed" — set by the worker at each
    # stage so GET /jobs/{id} can report progress before results exist.
    # "failed" (set from run_job_task's except clause) is what stops a job
    # that dies mid-run from looking identical to a slow-but-healthy one
    # forever — see app/queue/tasks.py.
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    hint_pack_name: Mapped[str | None] = mapped_column(String, nullable=True)
    notify_email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    call_results: Mapped[list[CallResultRow]] = relationship(back_populates="job")


class CallResultRow(Base):
    __tablename__ = "call_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    target: Mapped[str] = mapped_column(String, nullable=False)
    terminal_state: Mapped[str] = mapped_column(String, nullable=False)
    completion_level: Mapped[str | None] = mapped_column(String, nullable=True)
    reach_failure: Mapped[str | None] = mapped_column(String, nullable=True)
    refusal_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    fields: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    transcript: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    from_cache: Mapped[bool] = mapped_column(nullable=False, default=False)
    call_minutes: Mapped[float] = mapped_column(nullable=False, default=0.0)
    # Real per-call cost when the voice platform reports one — see
    # engine/models.py's CallResult.cost_usd. Was computed by the Retell
    # adapter and then dropped on the floor: this column didn't exist, so
    # every job lost its cost data between the call finishing and the
    # dashboard trying to show it.
    cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[JobRow] = relationship(back_populates="call_results")
