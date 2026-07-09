"""Job submission + results API — the P0 "ranked results table + per-call
transcript cards" surface, consumed by the dashboard.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_pool, get_session
from app.config import settings
from app.db import repository
from app.providers import build_provider_bundle
from engine.hint_packs import load_hint_pack
from engine.models import Request

router = APIRouter()


class JobSubmitBody(BaseModel):
    request: Request
    hint_pack: str | None = None
    notify_email: str | None = None
    # Set once the caller has seen missing_context from a prior submit and
    # wants to proceed anyway with partial context.
    acknowledge_missing_context: bool = False


@router.post("/jobs")
async def submit_job(
    body: JobSubmitBody,
    session: AsyncSession = Depends(get_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict[str, Any]:
    hint_pack = load_hint_pack(body.hint_pack) if body.hint_pack else None
    providers = build_provider_bundle(settings)
    brief = await providers.pre_call_brief.build_brief(body.request, hint_pack)

    # Missing needed context -> surfaced before any call, per CLAUDE.md's
    # acceptance criteria — no job is created until acknowledged.
    if brief.missing_context and not body.acknowledge_missing_context:
        return {"status": "needs_context", "brief": brief.model_dump(mode="json")}

    job_id = str(uuid4())
    await repository.create_job(session, job_id, body.request, body.hint_pack, body.notify_email)
    await arq_pool.enqueue_job(
        "run_job_task",
        job_id,
        body.request.model_dump(mode="json"),
        body.notify_email,
        _job_id=job_id,
    )
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    status_and_result = await repository.get_job(session, job_id)
    if status_and_result is None:
        raise HTTPException(status_code=404, detail="job not found")
    status, result = status_and_result
    return {
        "job_id": job_id,
        "status": status,
        "request": result.request.model_dump(mode="json") if result else None,
        "results": [r.model_dump(mode="json") for r in result.results] if result else None,
    }


@router.get("/jobs")
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    rows = await repository.list_jobs(session)
    return [
        {
            "job_id": row.id,
            "ask": row.request.get("ask"),
            "status": row.status,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
