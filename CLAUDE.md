# CLAUDE.md

Guidance for Claude Code when working in this repository.

---

## Project: Proxy — A Consumer's Outbound Voice Agent

**Thesis.** The entire voice-AI market is built for *businesses* to handle *customers*
— Retell, Vapi, Bland, Sierra, PolyAI all arm the company answering the phone. Almost
nobody has built the agent for the person on the *other* end: the one stuck in the
phone tree, getting screened, upsold, and stonewalled. Proxy is that agent — it makes
outbound calls to businesses *on the user's behalf*, runs the conversation, and returns
structured, confidence-scored results.

**Why now.** This is the 2018 Google Duplex demo that never shipped. Back then latency
and open-ended dialogue weren't good enough. In 2026 latency is ~600ms and LLMs handle
unscripted conversation — the tech finally caught up to the idea.

**Wedge vertical: rental screening.** The first configured use case is calling apartment
leasing offices to run a standardized screening interview and build a comparison across
properties. It is a *demo of the general pattern*, not the product. The engine is
vertical-agnostic; rental is config, not hardcode.

### Architectural implication of the thesis (read this twice)

The core engine must be **use-case-agnostic**. A vertical (rental, subscription
cancellation, bill dispute, appointment booking) is defined by a **config bundle**, never
by branching logic inside the engine. If adding a new vertical requires editing the
dialogue loop or the extractor, the abstraction has failed. The codebase itself is the
argument that this is a platform, not a rental app.

---

## Two failure modes that drive every decision

Do not regress on either — these come from real interview-loop feedback and are the
whole point of the project:

1. **Structured ambiguity handling.** When the other party gives a vague, partial, or
   contradictory answer ("rent's around 2k-ish, depends"), the system represents that
   ambiguity *as data* — it never silently coerces it into a clean value. Every extracted
   field carries a confidence score and a `needs_human_review` flag.
2. **Prompt robustness.** The agent handles interruptions, non-answers, rushed/hostile
   humans, IVR phone trees, and off-script tangents without derailing. Prompts are tested
   against adversarial and degenerate inputs, not just the happy path.

If a change makes extraction look more "confident" by hiding uncertainty, that is a
**regression**, not an improvement.

---

## Tech Stack

| Layer               | Choice                          | Notes |
|---------------------|---------------------------------|-------|
| Voice orchestration | **Pipecat** (Python)            | Own the STT→LLM→TTS pipeline + turn-taking. Do NOT outsource to Vapi/Retell — those are the *business-side* tools this project is a counterpoint to. |
| Telephony          | **Twilio** (Programmable Voice)  | Outbound calls + IVR/phone-tree navigation (DTMF). |
| STT                | **Deepgram** (streaming)         | Low-latency partials. Known quantity. |
| TTS                | **Cartesia** or **ElevenLabs**   | Pick one, keep swappable behind an interface. |
| LLM (dialogue)     | OpenAI `gpt-4o` / Anthropic      | Conversation policy + follow-up decisions. |
| LLM (extraction)   | Structured-output mode           | Separate call from dialogue. Pydantic-typed. |
| Backend / API      | **FastAPI** + async              | Call orchestration, job queue, results API. |
| Data models        | **Pydantic v2**                  | Single source of truth for schemas + vertical configs. |
| Persistence        | **Postgres** (SQLAlchemy async)  | Transcripts, extractions, runs. |
| Queue              | **Redis + arq**                  | Calls are long-running; never block the API. |
| Dashboard          | **Next.js (App Router) + TS**    | Results + per-call drill-down. Depth matters (see below). |
| Deploy             | Railway or Fly.io                | One-command deployable. |

**Alternative voice framework:** LiveKit Agents. Only swap if Pipecat's telephony/IVR
path proves painful. Flag the tradeoff before switching.

---

## Architecture

```
User picks a VERTICAL + provides targets ──▶ Job (N targets)
                                                   │
                                                   ▼
                                        [ Call Orchestrator ]  ── async, one call per target
                                                   │
                          ┌────────────────────────┴────────────────────────┐
                          ▼                                                  ▼
                 [ Pipecat pipeline ]                              [ Transcript store ]
        IVR nav → STT → Dialogue LLM → TTS                                  │
                          │                                                  │
                          ▼                                                  ▼
                 [ Turn-by-turn events ] ──────────────────▶ [ Extraction Pipeline ]
                                                              per-field, confidence-gated
                                                                       │
                                                                       ▼
                                                              [ Results Builder ]
                                                              (comparison / single result)
                                                                       │
                                                                       ▼
                                                  Dashboard (results + drill-down + review queue)
```

**Engine vs. vertical is the load-bearing boundary.** `engine/` knows nothing about
apartments. `verticals/rental/` supplies the goal, the question set, the extraction
schema, and the disclosure script. Same engine will later run `verticals/cancel_subscription/`.

---

## The Vertical abstraction (the core design bet)

A vertical is a config bundle, defined once, consumed by the generic engine:

```python
class Vertical(BaseModel):
    id: str                              # "rental"
    goal: str                            # natural-language objective for the dialogue agent
    disclosure_script: str               # legally-required "this is an AI calling on behalf of..." line
    question_set: list[Question]         # what to find out
    extraction_schema: type[BaseModel]   # generated from question_set — typed output shape
    result_mode: Literal["compare", "single"]  # comparison across targets vs. one outcome
```

Rules:
- The engine reads `Vertical` and runs. It contains **zero** `if vertical == "rental"` branches.
- The `extraction_schema` is generated *from* `question_set`, so adding a question doesn't
  require hand-editing the extractor.
- New vertical = new folder under `verticals/` + a config. No engine changes. If you find
  yourself editing `engine/`, stop and reconsider the abstraction.

---

## Core Design Principles

### 1. Confidence-gated extraction (non-negotiable)

Every extracted field follows this shape:

```python
class ExtractedField[T](BaseModel):
    value: T | None
    confidence: float                    # 0.0–1.0
    source_span: str | None              # verbatim transcript quote backing the value
    needs_human_review: bool
    reason: str | None                   # why review is needed, if flagged
```

- `confidence < THRESHOLD` (default 0.7) ⇒ `needs_human_review = True`; the value is
  surfaced *with a warning*, never silently dropped or silently trusted.
- No value without a `source_span`. If the agent can't point to where in the transcript
  the answer came from, it's a hallucination — set `value = None`.
- Contradictions within a call must produce a flagged field, not a coin-flip pick.

### 2. Structured ambiguity handling

The dialogue policy distinguishes:
- **Clear answer** → extract normally.
- **Ambiguous answer** → agent asks *one* targeted clarifying follow-up, then moves on.
- **Refused / unknown** → record `value=None, reason="declined"`, move on.

Never fabricate a plausible value to fill a gap. "Unknown" is a first-class outcome.

### 3. Prompt robustness

- All dialogue + extraction prompts live in `prompts/` as versioned files. Never inline.
- Every prompt ships with an adversarial test set: interruptions, silence, rushed/hostile
  reps, IVR phone trees, contradictory info, off-topic tangents, refusal to answer.
- Extraction prompts tested against degenerate transcripts (empty, single-word,
  wall-of-text, non-English fragments).

### 4. Act on the user's behalf, transparently

- The agent always opens with the vertical's `disclosure_script`: it identifies as an AI
  calling on behalf of a named person. No pretending to be human.
- The agent gathers information and reports back. It does **not** commit the user to
  anything (signing, paying, agreeing to terms) without an explicit human-in-the-loop
  approval step. Getting info is autonomous; making commitments is not.

---

## Dashboard Requirements (do not ship a toy)

First-class deliverable. Prior projects were dinged for shallow dashboards — do not repeat.

- **Results view** (comparison matrix for `compare` verticals; outcome card for `single`),
  with confidence indicated visually (muted/warning styling on low-confidence cells).
- **Drill-down**: click any value → see the `source_span` quote + surrounding transcript.
- **Review queue**: every `needs_human_review` field across all calls, filterable.
- **Call health**: per-call metrics (duration, turns, interruptions, IVR hops, % fields
  extracted, % flagged).

If a reviewer can't trace a value back to the exact words spoken, the dashboard is incomplete.

---

## Working Conventions

- **Plan first.** For any non-trivial change, write the plan (files, approach, tests)
  before editing. Confirm before large refactors or before touching `engine/`.
- **Incremental build-and-test.** Small verifiable steps; every new field/prompt ships
  with a test. Never batch a week of work into one commit.
- **Async everywhere** on the backend. Calls are long-running I/O — nothing blocks the loop.
- **Type everything.** Pydantic v2 + full hints. `mypy` clean.
- **Prompts are code.** Versioned, reviewed, tested. Never inline.
- **Secrets** via env only. Never commit keys.
- **Recorded calls / PII**: transcripts contain real people's voices and words. Store
  minimally, document retention, gate recording behind consent handling.

---

## Commands

```bash
# Setup
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Run backend API
uvicorn app.main:app --reload

# Run the voice agent worker (Pipecat pipeline)
python -m app.agent.worker

# Run a job locally (dev, mock telephony)
python -m app.cli run --vertical rental --targets examples/rental_targets.json

# Tests
pytest                          # unit + extraction tests
pytest tests/prompts -v         # adversarial prompt suite
pytest -m integration           # end-to-end with mocked STT/TTS

# Dashboard
cd dashboard && npm run dev

# Type + lint
mypy app/ && ruff check app/
```

---

## What NOT to do

- Do **not** put vertical-specific logic (`if vertical == "rental"`) inside `engine/`.
  That branch is the failure of the whole thesis.
- Do **not** replace the confidence/`source_span` machinery to "simplify." That machinery
  *is* the project.
- Do **not** coerce ambiguous or missing values into clean defaults.
- Do **not** move to a no-code voice platform (Vapi/Retell) — owning the pipeline is the point.
- Do **not** let the agent make binding commitments without human approval.
- Do **not** inline prompts or skip the adversarial test set when adding a field.

---

## Open questions to resolve early

- **Consent/recording law.** Outbound calls vary by state (WA is two-party consent).
  Finalize the `disclosure_script` per vertical before any real calls.
- **Chat-first fallback.** Some businesses prefer web chat/email. A text channel that
  reuses the same extraction pipeline de-risks the demo (not blocked on live-call plumbing)
  and doubles as a second proof the engine is channel-agnostic, not just vertical-agnostic.
- **Wedge choice.** Rental is a great *visual* demo but low-frequency. Higher-frequency /
  higher-emotion verticals (cancel/negotiate a subscription, dispute a bill) may show the
  thesis better. Keep rental as the demo; design the config layer so these are trivial to add.