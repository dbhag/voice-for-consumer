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
from engine.hint_packs import load_hint_pack, select_hint_pack
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
    # The caller (dashboard) never names a pack explicitly — resolved from
    # the ask so the form doesn't have to expose internal hint-pack naming.
    # An explicit body.hint_pack (CLI/API callers) still wins if given.
    hint_pack_name = body.hint_pack or select_hint_pack(body.request.ask)
    hint_pack = load_hint_pack(hint_pack_name) if hint_pack_name else None
    providers = build_provider_bundle(settings)
    brief = await providers.pre_call_brief.build_brief(body.request, hint_pack)

    # A context value the brief judged to be a non-answer ("not sure", "n/a"...)
    # must never reach the call as a stated fact — dropped unconditionally,
    # regardless of which branch below runs, so it's true for every path a
    # job can be created through. See engine/models.py's
    # PreCallBrief.dropped_context_keys.
    #
    # brief.return_fields is the whole point of the brief step (e.g.
    # splitting a compound ask like "price and tour availability" into
    # separate facts) — applying it only to the missing-context check below
    # and then discarding it would make that refinement invisible to the
    # call that actually runs. Rebuilt via model_validate, not model_copy,
    # so return_fields goes back through Request's normalizer (snake_case +
    # compound-split) — model_copy(update=...) skips validators, and the
    # brief's own field names aren't guaranteed to already be normalized.
    request = Request.model_validate(
        {
            **body.request.model_dump(mode="json"),
            "context": {
                k: v
                for k, v in body.request.context.items()
                if k not in brief.dropped_context_keys
            },
            "return_fields": brief.return_fields or body.request.return_fields,
        }
    )

    # Missing needed context -> surfaced before any call, per CLAUDE.md's
    # acceptance criteria — no job is created until acknowledged.
    if brief.missing_context and not body.acknowledge_missing_context:
        return {"status": "needs_context", "brief": brief.model_dump(mode="json")}

    job_id = str(uuid4())
    await repository.create_job(session, job_id, request, hint_pack_name, body.notify_email)
    await arq_pool.enqueue_job(
        "run_job_task",
        job_id,
        request.model_dump(mode="json"),
        hint_pack_name,
        body.notify_email,
        _job_id=job_id,
    )
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    status_and_result = await repository.get_job(session, job_id)
    if status_and_result is None:
        raise HTTPException(status_code=404, detail="job not found")
    status, error, result = status_and_result
    return {
        "job_id": job_id,
        "status": status,
        "error": error,
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
