from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.jobs import router as jobs_router
from app.config import settings
from app.db.session import make_engine, make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = make_engine()
    app.state.session_factory = make_session_factory(engine)
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    yield
    await app.state.arq_pool.aclose()
    await engine.dispose()


app = FastAPI(title="Proxy", lifespan=lifespan)
# The dashboard is a separate origin (localhost:3000 vs the API's :8000) —
# without this, every browser-side fetch in dashboard/lib/api.ts fails with
# a generic "TypeError: Failed to fetch" (no preflight response, no
# Access-Control-Allow-Origin header), not a helpful CORS error message.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
