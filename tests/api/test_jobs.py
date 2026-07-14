from __future__ import annotations

from typing import Any

import fakeredis.aioredis as fakeaioredis
import pytest
from arq.connections import ArqRedis
from arq.worker import Worker
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_arq_pool, get_session
from app.db.models import Base
from app.db.session import make_session_factory
from app.main import app
from app.notifications import MockNotificationProvider
from app.queue.tasks import run_job_task
from engine.cache import InMemoryCacheStore
from tests.conftest import make_test_engine


@pytest.fixture
async def sqlite_session_factory():
    # Name kept for compatibility with the rest of this file — defaults to
    # SQLite but honors TEST_DATABASE_URL, see tests/conftest.py.
    engine = make_test_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield make_session_factory(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def fake_arq_pool():
    fake = fakeaioredis.FakeRedis()
    pool = ArqRedis(connection_pool=fake.connection_pool)
    yield pool
    await pool.aclose()


@pytest.fixture
async def client(sqlite_session_factory, fake_arq_pool: ArqRedis):
    # httpx.AsyncClient over ASGITransport, not the sync TestClient: the sync
    # TestClient runs requests through its own anyio portal loop, separate
    # from this test coroutine's event loop. That's harmless for
    # aiosqlite (not loop-bound the same way), but a real asyncpg
    # connection — loop-bound at the C level — raises "attached to a
    # different loop" the moment a request handler tries to use it. Driving
    # everything from one AsyncClient keeps engine and requests on one loop
    # regardless of which DB backend TEST_DATABASE_URL points at.
    async def override_get_session():
        async with sqlite_session_factory() as session:
            yield session

    async def override_get_arq_pool() -> ArqRedis:
        return fake_arq_pool

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_arq_pool] = override_get_arq_pool
    # No lifespan (`async with AsyncClient(...) as c:` alone doesn't run
    # app/main.py's lifespan either) — that would open a real Redis
    # connection. Dependency overrides above make that state unnecessary.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def _drain_queue(fake_arq_pool: ArqRedis, sqlite_session_factory) -> None:
    async def on_startup(ctx: dict[str, Any]) -> None:
        ctx["session_factory"] = sqlite_session_factory
        ctx["cache"] = InMemoryCacheStore()
        ctx["notification"] = MockNotificationProvider()

    async def on_shutdown(ctx: dict[str, Any]) -> None:
        pass

    async def _no_op_log_redis_info(*args: Any, **kwargs: Any) -> None:
        pass

    import arq.worker

    arq.worker.log_redis_info = _no_op_log_redis_info  # type: ignore[assignment]

    worker = Worker(
        functions=[run_job_task],
        redis_pool=fake_arq_pool,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        burst=True,
        poll_delay=0,
    )
    await worker.main()
    await worker.close()


def _auto_repair_request(**overrides: Any) -> dict[str, Any]:
    base = {
        "ask": "quote for front brake pad replacement",
        "return_fields": ["price", "parts_vs_labor", "earliest_availability"],
        "context": {"car": "2018 Honda Civic", "mileage": 82000, "symptom": "squealing"},
        "targets": ["+15550000001", "+15550000005", "+15550000004"],
    }
    base.update(overrides)
    return base


async def test_missing_context_is_surfaced_before_any_job_is_created(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/jobs",
        json={
            "request": _auto_repair_request(context={}),
            "hint_pack": "auto_repair",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_context"
    assert len(body["brief"]["missing_context"]) > 0

    assert (await client.get("/jobs")).json() == []


async def test_full_job_lifecycle_submit_drain_and_read_back(
    fake_arq_pool: ArqRedis, sqlite_session_factory
) -> None:
    # httpx.AsyncClient over ASGITransport, not the sync TestClient: the sync
    # TestClient runs requests through its own anyio portal loop, separate
    # from this test coroutine's event loop — the fakeredis pool (an asyncio
    # fixture bound to this test's loop) would then get touched from two
    # different event loops and raise "bound to a different event loop".
    # Driving everything from one AsyncClient keeps it all on one loop.
    async def override_get_session():
        async with sqlite_session_factory() as session:
            yield session

    async def override_get_arq_pool() -> ArqRedis:
        return fake_arq_pool

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_arq_pool] = override_get_arq_pool
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/jobs",
                json={
                    "request": _auto_repair_request(),
                    "hint_pack": "auto_repair",
                    "notify_email": "user@example.com",
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "queued"
            job_id = body["job_id"]

            running = (await client.get(f"/jobs/{job_id}")).json()
            assert running["status"] in ("queued", "running")
            assert running["results"] is None

            await _drain_queue(fake_arq_pool, sqlite_session_factory)

            done = (await client.get(f"/jobs/{job_id}")).json()
            assert done["status"] == "done"
            terminal_states = {r["terminal_state"] for r in done["results"]}
            assert terminal_states == {"got_info", "refused", "couldnt_reach"}

            jobs = (await client.get("/jobs")).json()
            assert len(jobs) == 1
            assert jobs[0]["job_id"] == job_id
            assert jobs[0]["status"] == "done"
    finally:
        app.dependency_overrides.clear()


async def test_unknown_job_id_is_404(client: AsyncClient) -> None:
    response = await client.get("/jobs/does-not-exist")
    assert response.status_code == 404
