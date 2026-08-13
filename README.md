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

## The `VoicePlatformProvider` seam — and where it leaks

### The seam

`VoicePlatformProvider` (`engine/providers/base.py:62`) is a Protocol with exactly one
method: `start_call(request, phone_number) -> VoiceCallSession`. It's deliberately thin
because it marks a **purchase boundary, not a capability boundary**. The vendor
(Retell/Bland/Vapi) owns telephony + STT + in-call dialogue LLM + TTS + turn-taking as one
bought product (`base.py:3-7`); the engine never integrates Twilio/Deepgram/Cartesia
directly. The richer surface — `classify` / `navigate_menu` / `wait_on_hold` /
`request_callback` / `converse` / `hangup` — lives on `VoiceCallSession` (`base.py:30`),
which models a single call as a sequence of steps the **caller** drives:
`engine/call_loop.py`'s state machine calls `classify()`, branches into
`navigate_menu()` / `wait_on_hold()`, then `converse(DISCLOSURE, ask, context)`
(`call_loop.py:74`), then `hangup()`.

### Where it leaks

The Protocol assumes the caller drives the session step by step, feeding the disclosure,
primary question, and context into `converse()` to steer a live conversation. **Retell
inverts that.** `RetellVoicePlatformProvider.start_call()` (`retell.py:333`) posts one
`/v2/create-phone-call` with all context front-loaded into `retell_llm_dynamic_variables`
(`retell.py:337`); the entire conversation is fixed at call-creation time and runs to
completion inside Retell's own agent before our code observes anything. What the adapter
does to reconcile that, and what each reconciliation costs:

- **`classify()` is retroactive, not a live check.** `RetellVoiceCallSession.classify()`
  (`retell.py:227`) calls `_fetch_finished_call()` (`retell.py:188`), which *blocks* —
  polling `get-call` — until `call_status` is `ended`/`error` and `call_analysis` has
  populated. It only returns *after the whole call already happened*, and can only ever
  return `HUMAN` or `VM_NO_ANSWER_BUSY` (`retell.py:231-238`) — never `IVR` or `HOLD`.
- **Three of the six session methods are unreachable and raise.** Because `classify()`
  never returns `IVR`/`HOLD`, `navigate_menu()` (`retell.py:240`), `wait_on_hold()`
  (`retell.py:247`), and `request_callback()` (`retell.py:255`) each `raise RuntimeError`
  if called. The one real adapter cannot honor half the Protocol it nominally implements.
  It's a loud failure by design, but the interface advertises capabilities the vendor
  doesn't provide: the IVR-navigation and callback branches of `call_loop`'s state machine
  — and the `CALLBACK_PENDING` cost-saver they exist for — are dead code on every real call.
- **`converse()`'s arguments are ignored.** `call_loop.py:74` passes `DISCLOSURE` (the
  constant at `call_loop.py:29`), `request.ask`, and `request.context` into `converse()`.
  `RetellVoiceCallSession.converse()` (`retell.py:261`) accepts all three and uses none of
  them — the call already ran using whatever `build_dynamic_variables()` baked in at
  `start_call` (`retell.py:264-267`); it just translates the finished transcript. Concrete
  footgun: **editing the `DISCLOSURE` constant in `call_loop.py` has zero effect on a
  Retell call.** The disclosure Retell actually speaks comes from the agent's configured
  system prompt (`prompts/dialogue/v1/system.txt`, loaded into the Retell dashboard out of
  band), not from any argument this code passes.
- **`hangup()` is a no-op** (`retell.py:304`): there's no live call left to hang up by the
  time the loop reaches it. A caller cannot end a call early through the Protocol.
- **`hold_abandon_seconds` never engages.** `call_loop`'s hold-abandon cost guardrail
  wraps `wait_on_hold()`, which is unreachable — so it's inert for Retell (see the
  mechanism table below). Retell's own `poll_timeout_seconds` (`retell.py:319`, default
  600s) is a *different* knob; misconfiguring one does not protect the other.
- **Refusal detection depends on out-of-band vendor config.** `converse()` reads
  `refused_to_quote` from `call_analysis.custom_analysis_data` (`retell.py:292-296`). That
  field only exists if the Retell agent was configured — in the Retell dashboard, outside
  this repo — with a matching custom post-call-analysis schema. If it wasn't, the key is
  absent and every call silently reads as *not refused* (`retell.py:271-278`); there's no
  way to distinguish "agent wasn't configured to detect this" from "genuinely wasn't
  refused" from our side.

Net: for a Retell call the "session" isn't a session — it's a blocking post-mortem reader
of a call that already finished. `classify()` holds its concurrency-cap slot for the
call's entire real duration (see Known tradeoffs below), `converse()`'s inputs are inert,
and four of the six `VoiceCallSession` methods are either no-ops or hard errors.

### Progress Update

One real provider (Retell) plus a mock (`engine/providers/mock.py`). **Bland and Vapi
appear only in comments** (`base.py:3`, `mock.py:4`, `app/agent/worker.py`) — named as
evaluation candidates, never implemented; there is no Bland or Vapi adapter in the repo.

The Retell **happy path** — `classify()` returning `HUMAN`/`VM_NO_ANSWER_BUSY`, then
`converse()` translating the finished transcript, then extraction — has been run against
10 real Seattle auto shops (real businesses, not the self-call used earlier). That covers
only the part of the Protocol the adapter can actually reach. The rest of the step-driven
surface — `classify` returning `IVR`/`HOLD`, `navigate_menu`, `wait_on_hold`,
`request_callback`, and the `call_loop` branches and cost-savers built on them — is still
exercised **only** by the mock's canned scenarios (`mock.py`), and can't be validated
through Retell at all, because the one real vendor can't reach it (see "Where it leaks").

The inversion is early evidence the seam may be at the wrong altitude. The Protocol models
a call as a sequence of steps the caller drives; the one real vendor integrated so far runs
the call atomically and can only be read after the fact. We cannot yet tell whether that's
a Retell-specific impedance or a wrong abstraction: with n=1 real adapter there's no way to
know whether Bland or Vapi would fit the drivable-session shape or invert it the same way.
If a second real vendor also inverts it, the Protocol is modeling the wrong thing. Until one
is implemented, that's unverified — flagged, not resolved.

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
