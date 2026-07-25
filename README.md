# Proxy

## Overview

A consumer's outbound voice agent. Proxy calls businesses **on the user's behalf** —
the opposite of Vapi/Retell/Bland, which arm the business answering the phone. The
user supplies phone numbers + context; Proxy places the calls, survives the IVR and
hold, gathers the answers, and reports back a ranked, transcript-backed result.

v1's test vertical is auto repair (get a quote for a repair by phone) — a demo of the
general pattern, not the product. See [CLAUDE.md](CLAUDE.md) for the full spec and
non-negotiable principles (the no-fabrication hard rule, the pre-call brief, the
cache, the proof/transcript layer).

## Architecture

*(placeholder — expand on the engine/provider split and why)*

The engine is vertical-agnostic: there is no vertical logic in code anywhere in
`engine/`. Per-vertical differences (e.g. "auto repair shops will ask
year/make/model/mileage") live only as data in `hint_packs/`, never as an `if` branch.
Providers (`engine/providers/base.py`'s Protocols) are the seam between that generic
engine and bought infrastructure (voice platform, LLM) — swapping `mock` for `retell`
or `fake` for `openai` in `app/config.py` never touches orchestration code.

- `engine/` — vertical-agnostic core: the call state machine (`call_loop.py`,
  `orchestrator.py`), the cache (`cache.py`), the hard-rule grounding choke point
  (`extraction.py`), the pre-call brief (`pre_call_brief.py`), provider protocols
  (`providers/base.py`) with mock (`providers/mock.py`), real LLM-backed
  (`providers/llm_*.py`), and real voice-platform (`providers/retell.py`)
  implementations.
- `hint_packs/` — plain-data per-vertical completeness checks (e.g. `auto_repair.json`).
  Adding a vertical means adding a hint pack, never touching `engine/`.
- `prompts/` — versioned prompt files (`dialogue/`, `extraction/`, `pre_call_brief/`,
  `audit/`), never inlined as Python strings.
- `app/` — thin orchestration layer: FastAPI routes (`api/routes/jobs.py`), the arq
  queue worker (`queue/tasks.py`), DB persistence (`db/repository.py`), notifications
  (`notifications.py`), and the provider factory that switches mock↔real per
  `app/config.py` settings (`providers.py`).
- `dashboard/` — Next.js (App Router) job submission form + ranked-results/transcript
  UI, talking to the FastAPI backend over `NEXT_PUBLIC_API_BASE_URL`.
- `scripts/` — dev-environment bootstrap (`db_setup.sh`, `init_schema.py`,
  `run_fakeredis.py`), not application code.

## Setup & running

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

cd dashboard && npm install
```

The whole stack — fakeredis (TCP) → API → arq worker → dashboard, each gated on its
own readiness check — comes up with one command:

```bash
./dev.sh --mock   # or: DEV_MOCK=1 ./dev.sh, or: make dev (reads DEV_MOCK from env)
```

`--mock` forces `VOICE_PLATFORM_PROVIDER=mock` and `LLM_PROVIDER=fake` for the run,
overriding whatever `.env` says.

> **WARNING:** running `./dev.sh` *without* `--mock` uses whatever `.env` has set for
> `VOICE_PLATFORM_PROVIDER` / `LLM_PROVIDER`. If those are real (Retell / OpenAI —
> check `.env` before running), the stack will spend real LLM tokens and **can place
> a real outbound phone call**. Never the default for a local dry run — `--mock` is
> the safe path; real providers are an explicit, deliberate opt-in.

`dev.sh` also idempotently bootstraps the local Postgres role/db/schema it needs
(`scripts/db_setup.sh` — same thing `make db-setup` runs standalone) and always talks
to its own fakeredis TCP server, never a real Redis. Ctrl+C tears down all four
processes cleanly. Logs land in `.dev-logs/`.

For a one-shot offline demo without the API/worker/dashboard:

```bash
python -m app.cli run --request examples/auto_repair_request.json --hint-pack auto_repair
```

To point the stack at real infra instead of fakeredis (e.g. to test against Postgres
in Docker): `docker compose up -d` brings up both Postgres and Redis
(`docker-compose.yml`).

### Tests

```bash
pytest                                    # full suite (mock providers, in-memory SQLite)
pytest -m integration                     # opt-in: real OpenAI/Anthropic extraction calls
mypy app/ engine/ && ruff check app/ engine/
cd dashboard && npm run lint && npm run build
```

`tests/db/`, `tests/queue/`, and `tests/api/` default to an in-memory SQLite DB and a
fakeredis-backed queue, so the whole suite runs with nothing external installed. To
validate against a real Postgres instead — worth doing at least once; SQLite silently
tolerated a naive/timezone-aware datetime mismatch that real Postgres rejected outright
(see Known tradeoffs below):

```bash
docker compose up -d postgres
until docker compose exec postgres pg_isready -U proxy; do sleep 1; done
TEST_DATABASE_URL=postgresql+asyncpg://proxy:proxy@localhost:5432/proxy \
  pytest tests/db/test_repository.py tests/queue/test_tasks.py tests/api/test_jobs.py
```

## Results

*(placeholder — real-call completion rate, filled from live Retell calls)*

## Findings & limitations

*(placeholder — to be written)*

**Structural limit, not a bug: the hard rule can't catch a wrong fact, only a fabricated
one.** The pre-call brief (`engine/pre_call_brief.py`'s `detect_non_answer_context`,
`engine/providers/llm_pre_call_brief.py`) now drops context values that read as a
non-answer ("not sure", "n/a"...) before they ever reach a call — see the hard-rule
findings below for what that does and doesn't cover. It stops "not sure" from being
spoken as if it were the customer's actual answer. It does nothing for a value the user
typed *confidently and wrong* — 82,000 miles keyed in for a car that actually has
120,000. That string is indistinguishable from a real fact to the brief, the agent, and
the hard rule alike; all three trust the context bundle by design (CLAUDE.md: the hard
rule stops the agent from *inventing* a fact, not from repeating a bad one it was
handed). Catching that would need external verification against a source of truth the
system doesn't have — out of scope for v1, worth stating plainly rather than implying
"hard rule" covers more than it does.

## Known tradeoffs from the build-vs-buy decision

Engine, cache, hard rule, pre-call brief, cost guardrails (concurrency cap, per-job
minute budget, hold-abandon timeout), API, queue, DB persistence, and notifications
are all real and tested. `voice_platform_provider="retell"`
(`engine/providers/retell.py`) is a real adapter against Retell's API, tested against
a stubbed HTTP layer (no real calls placed in the test suite) — not yet exercised
against a live Retell account. `voice_platform_provider="mock"` stays the default. The
disclosure script in `engine/call_loop.py`'s `DISCLOSURE` constant is a placeholder
pending final consent-language sign-off.

**Retell's phone-call API is one atomic operation** — `create-phone-call` kicks off a
call that Retell's own agent runs end to end (disclosure, any IVR nav, hold,
conversation, hangup) with no mid-call checkpoint exposed to us. Our
`VoiceCallSession` Protocol models a call as discrete steps (`classify` →
`navigate_menu` / `wait_on_hold` → `converse`). `engine/providers/retell.py`
reconciles the two by having `classify()` block (polling `get-call`) until Retell
reports the call has actually ended, then classifying retroactively. That has real,
documented (not hidden) consequences for which of the engine's guardrails and states
actually engage:

| Mechanism | Retell | Why |
|---|---|---|
| `job_minute_budget` | **Enforces** | Lives in `orchestrator.py`, purely wall-clock/provider-agnostic; the wall-clock span it measures includes Retell's full blocking poll, so real call time is captured correctly. |
| `concurrency_cap` | **Enforces** (more critically than for mock) | Also provider-agnostic — but for Retell, one semaphore slot is held for an entire real call's duration, not mock's near-instant resolution. It's the primary real cost/rate-limit control here, not a nicety. |
| `hold_abandon_seconds` | **Dead code** | Only invoked when `classify()` returns `HOLD`. Retell's `classify()` never returns anything but `HUMAN`/`VM_NO_ANSWER_BUSY` — it retroactively classifies an already-finished call. |
| `NAVIGATE_MENU` / IVR state | **Dead code** | Same cause: `classify()` never returns `IVR`, so `navigate_menu()` is never called (it exists only to raise `RuntimeError` if that ever changed). |
| `REQUEST_CALLBACK` | **Dead code**, doubly so | Same cause, *plus* inbound-callback resumption into `CONVERSE` isn't built anywhere yet (mock included) — still P1 per CLAUDE.md, so there'd be nothing to resume into even if Retell surfaced a callback offer. |

**Could HOLD/IVR/callback be made real for Retell?** Not within this integration shape.
It would need Retell to expose live mid-call state (a webhook/event stream: "on hold
now," "IVR menu detected") *and* a control API to act on it in real time — the
`create-phone-call` + `get-call` pair this adapter uses doesn't have that. Retell does
offer a different integration mode (a custom-LLM websocket connection where you drive
turn-by-turn state yourself), but building against that means taking on the real-time
turn-taking control loop the buy-not-build stack decision was explicitly meant to avoid.
Separately unverified: whether Retell's standard agent navigates IVR trees autonomously
on its own — plausible for a voice-AI product, but not confirmed either way here.

**Refusal detection is Retell's, not ours.** Retell has no built-in "declined to quote"
signal — `converse()` in `engine/providers/retell.py` depends entirely on the Retell
agent being configured (in the Retell dashboard) with a custom post-call analysis field
named `refused_to_quote` (+ optional `refusal_reason`). If that schema isn't configured
on the agent, `custom_analysis_data` won't have the key and the call always reads as
not-refused — a real gap, not a guess: there's no way to distinguish "agent wasn't
configured to detect this" from "genuinely wasn't refused" from our side. Deliberately
not re-derived from transcript text with a second, independent keyword heuristic in
this adapter — that would just relocate the same class of bug (a naive text match
misreading an ambiguous/mis-transcribed word) rather than fix it; the fix for that
belongs in the prompt (`prompts/dialogue/v1/system.txt`'s consent-gate paragraph), not
a patch in the adapter.

**SQLite-only tests hid a real Postgres-only bug.** `app/db/models.py`'s
`created_at`/`started_at`/`ended_at` columns were declared as naive `DateTime`, while
the code populating them (`datetime.now(UTC)`, `engine/call_loop.py`) is
timezone-aware. SQLite doesn't enforce column-level timezone strictness, so the full
test suite (in-memory SQLite by default) passed cleanly for as long as it ran only
against SQLite. The first real Postgres write (`asyncpg`) rejected it outright: `can't
subtract offset-naive and offset-aware datetimes`. Fixed by declaring the columns
`DateTime(timezone=True)`. This is the concrete argument for the `TEST_DATABASE_URL`
real-Postgres test pass above — mock/lightweight test infra can and did diverge from
the real dependency's behavior.
