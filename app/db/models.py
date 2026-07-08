"""SQLAlchemy ORM tables mirroring the engine's Pydantic domain models.

Importable only in this pass — no live DB connection or migration is
required for `app.cli run` to work. Wiring these up (Alembic migration,
session usage in orchestrator persistence) lands once `app/api` needs to
read job history back.
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
    vertical_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    call_results: Mapped[list[CallResultRow]] = relationship(back_populates="job")


class CallResultRow(Base):
    __tablename__ = "call_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    transcript: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    extracted: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job: Mapped[JobRow] = relationship(back_populates="call_results")
