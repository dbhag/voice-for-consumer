# Proxy

A consumer's outbound voice agent. Proxy calls businesses **on the user's behalf** —
the opposite of Vapi/Retell/Bland, which arm the business answering the phone. The
user supplies phone numbers + context; Proxy places the calls, survives the IVR and
hold, gathers the answers, and reports back a ranked, transcript-backed result.

v1's test vertical is auto repair (get a quote for a repair by phone) — a demo of the
general pattern, not the product. The engine is vertical-agnostic: there is no
vertical logic in code anywhere in `engine/`. Per-vertical differences (e.g. "auto
repair shops will ask year/make/model/mileage") live only as data in `hint_packs/`.
See [CLAUDE.md](CLAUDE.md) for the full spec and non-negotiable principles (the
no-fabrication hard rule, the pre-call brief, the cache, the proof/transcript layer).

## Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

cd dashboard && npm install
```

## Running it locally

Everything below defaults to mock/deterministic backends — no API keys, no network,
no real Redis/Postgres required.

```bash
# One-shot offline demo: full call-state-machine loop against mock providers
python -m app.cli run --request examples/auto_repair_request.json --hint-pack auto_repair

# Full stack: API + queue worker + dashboard
uvicorn app.main:app --reload         # backend API (needs Redis; see below)
arq app.queue.tasks.WorkerSettings    # job worker (needs Redis)
cd dashboard && npm run dev           # job submission + ranked-results UI
```

`uvicorn`/`arq` need a real Redis (`redis_url` in `app/config.py`, default
`redis://localhost:6379/0`) and Postgres (`database_url`, default
`postgresql+asyncpg://proxy:proxy@localhost:5432/proxy`) reachable. For local
Postgres: `docker compose up -d postgres` (see `docker-compose.yml`). There's no
docker-compose entry for Redis yet — point `REDIS_URL` at any local Redis, or see
`tests/queue/test_tasks.py` for how the test suite fakes one out.

## Tests

```bash
pytest                                    # full suite (mock providers, in-memory SQLite)
pytest -m integration                     # opt-in: real OpenAI/Anthropic extraction calls
mypy app/ engine/ && ruff check app/ engine/
cd dashboard && npm run lint && npm run build
```

`tests/db/`, `tests/queue/`, and `tests/api/` default to an in-memory SQLite DB and a
fakeredis-backed queue, so the whole suite runs with nothing external installed. To
validate against a real Postgres instead (SQLite's JSON columns are TEXT under the
hood — worth checking at least once):

```bash
docker compose up -d postgres
until docker compose exec postgres pg_isready -U proxy; do sleep 1; done
TEST_DATABASE_URL=postgresql+asyncpg://proxy:proxy@localhost:5432/proxy \
  pytest tests/db/test_repository.py tests/queue/test_tasks.py tests/api/test_jobs.py
```

## Architecture

- `engine/` — vertical-agnostic core: the call state machine (`call_loop.py`,
  `orchestrator.py`), the cache (`cache.py`), the hard-rule grounding choke point
  (`extraction.py`), the pre-call brief (`pre_call_brief.py`), provider protocols
  (`providers/base.py`) with mock (`providers/mock.py`) and real LLM-backed
  (`providers/llm_*.py`) implementations.
- `hint_packs/` — plain-data per-vertical completeness checks (e.g. `auto_repair.json`).
  Adding a vertical means adding a hint pack, never touching `engine/`.
- `prompts/` — versioned prompt files (`dialogue/`, `extraction/`, `pre_call_brief/`),
  never inlined as Python strings.
- `app/` — thin orchestration layer: FastAPI routes (`api/routes/jobs.py`), the arq
  queue worker (`queue/tasks.py`), DB persistence (`db/repository.py`), notifications
  (`notifications.py`), and the provider factory that switches mock↔real per
  `app/config.py` settings (`providers.py`).
- `dashboard/` — Next.js (App Router) job submission form + ranked-results/transcript
  UI, talking to the FastAPI backend over `NEXT_PUBLIC_API_BASE_URL`.

## Build status

Engine, cache, hard rule, pre-call brief, cost guardrails (concurrency cap, per-job
minute budget, hold-abandon timeout), API, queue, DB persistence, and notifications
are all real and tested (unit tests plus live process-level runs — see git history for
details). `voice_platform_provider` stays mocked (`engine/providers/mock.py`) pending a
Bland/Retell/Vapi evaluation — that's the one seam left deliberately unfilled;
everything else in `engine/providers/base.py`'s `VoicePlatformProvider` interface is
already in place for a real adapter to drop in without touching the rest of the
engine. The disclosure script in `engine/call_loop.py`'s `DISCLOSURE` constant is a
placeholder pending final consent-language sign-off.
