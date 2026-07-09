# CLAUDE.md

Operational guidance for Claude Code in this repository. This file encodes the v1
product spec's decisions. When code and spec disagree, the spec wins — flag the conflict.

---

## Project: Proxy — v1 "Quote-Getter"

A **consumer outbound calling agent**. The user supplies phone numbers + context; the
agent places the calls, survives the IVR and hold, gathers the answers, and reports back
a ranked result. **Read-only, disclosed, async, one metro.**

**Thesis.** The whole voice-AI market arms *businesses* against *customers* (Retell, Vapi,
Bland, Sierra all answer calls for companies). Proxy is the agent for the person on the
other end — it makes the calls *for the user*. v1 proves the engine on phone-locked info
(quotes, live availability, off-web prices).

**v1 test vertical:** auto repair (bounded calls, predictable follow-ups, shops quote by
phone). The product is **not committed to it** — the engine is generic.

### The moat is NOT the pipeline

Four things are the moat, and they are where engineering effort goes:
1. **The pre-call brief** (front-loading context so calls don't fail mid-conversation).
2. **The hard-rule agent behavior** (never fabricate a user fact).
3. **The proof/report layer** (transcript-backed, trustable results).
4. **The cache** (per-business answer store — bends cost from linear to sublinear).

STT / TTS / latency / turn-taking are **bought, not built** (see Stack). Do not spend
timeline there — it is undifferentiated infrastructure.

---

## Stack (build-vs-buy — READ THIS before proposing architecture)

**Do NOT build the voice pipeline.** Build on a voice-infra platform that provides
telephony + STT + LLM + TTS + turn-taking as one product.

| Layer            | Choice | Notes |
|------------------|--------|-------|
| Voice infra      | **Bland / Retell / Vapi** — evaluate on latency, IVR navigation, per-minute cost | All support parallel calls + transcripts. Prefer BYO-component (Vapi-style) for stack-routing control (see Cost). |
| Telephony        | Provided by platform (Twilio underneath) | BYO SIP trunk is a volume-era optimization, not v1. |
| Pre-call brief   | One LLM call (OpenAI/Anthropic) | The highest-leverage step in the product. |
| Job orchestration| Queue + worker (Redis + arq / Celery) | Fan out calls under a concurrency cap, collect results. |
| App front        | **Next.js / React** | Web only. No mobile in v1. |
| Backend          | **FastAPI** + async | Thin — orchestrate jobs, serve results. |
| Data models      | **Pydantic v2** | Source of truth for the request object + extraction shapes. |
| Storage          | Postgres | Transcripts, terminal states, request objects, keyed answer cache. **No sensitive PII by design.** |
| Notifications    | SMS (Twilio) or email | Async completion ping. |
| Deploy           | Railway / Fly.io | One-command deployable. |

> This reverses an earlier "own the pipeline" stance. Intentional: solo founder proving
> an engine. Owning the pipeline is a post-PMF decision, not a v1 one.

---

## The Three-Part Input (the completion-rate driver)

Completion rate lives or dies on the fact that **businesses ask questions back**. The
input is never just "the question":

1. **The ask** — plain language ("quote to replace front brake pads").
2. **The context bundle** — facts for likely follow-ups (year/make/model, mileage, symptom).
3. **The targets** — the phone numbers (user-supplied in v1; auto-discovery is v2).

### Request object (generic — NO vertical hardcoded)

```python
{
  "ask": "quote for front brake pad replacement",
  "return_fields": ["price", "parts_vs_labor", "earliest_availability"],
  "context": {"car": "2018 Honda Civic", "mileage": 82000, "symptom": "squealing"},
  "boundaries": {"read_only": True, "do_not_share": ["full_name"]},
  "targets": ["+1XXXXXXXXXX", "+1XXXXXXXXXX", "+1XXXXXXXXXX"]
}
```

The agent handles follow-ups **dynamically** — the LLM reasons from the context bundle in
real time, governed by the hard rule below. No vertical logic in code. Per-vertical "hint
packs" (auto → ask year/make/model/mileage) are a **data-driven bolt-on** to enrich the
brief's completeness check — never a code branch.

---

## Pre-Call Brief (P0 — highest-leverage feature)

On submit, one LLM call pre-processes the ask into: the **primary question**, the
**return fields**, the **likely follow-ups**, and a **missing-context check** surfaced to
the user *before dialing* ("Shops will likely ask year, make, model, mileage — add these").
This is the difference between ~40% and ~80% completion. Build it first.

---

## Call State Machine (each call = independent run; log terminal state for all)

```
CACHE_CHECK  (before spending a single minute)
  └─ fresh cached answer for (business, question) within TTL? → terminal: GOT_INFO (cached, $0)
     else → DIAL

DIAL
  └─ CLASSIFY_ANSWER ── human ───→ CONVERSE
                     ── IVR ─────→ NAVIGATE_MENU → (hold | human | callback option)
                     ── hold ────→ WAIT_ON_HOLD → (human returns) | REQUEST_CALLBACK
                     ── vm/no-answer/busy → terminal: COULDNT_REACH  (leave NO message)

REQUEST_CALLBACK (cost-saver):
  IVR offers "press N, we'll call you back" → take it, hang up (STOP THE METER),
  await inbound callback → on callback → CONVERSE

CONVERSE:
  disclose (AI assistant calling for a customer)
  → ask primary question → handle follow-ups (hard rule) → extract return_fields
  → close politely → terminal: GOT_INFO (full | partial)

Blocked (won't quote by phone / hard-gated on a missing fact):
  → close politely, log reason → terminal: REFUSED
```

Terminal states are first-class results, not errors. `COULDNT_REACH` and `REFUSED`
appear clearly in the UI as outcomes, never as crashes.

---

## The Hard Rule (P0 — non-negotiable, has a negative test)

When a business asks for a fact **not in the context bundle**, the agent states it doesn't
have it / marks the field unknown. **It never fabricates a user fact.**

Negative test that must pass: no invented car year, name, mileage, or account detail
appears in *any* transcript. This is the trust foundation of the whole product — a
fabricated fact on a real call to a real business is the worst failure mode.

Corollary for extraction: every returned value is backed by the transcript. If the agent
can't ground a `return_field` in what was actually said, it returns unknown, not a guess.
(Per-field confidence scoring — flagging soft vs. firm quotes — is a P1 enhancement, not
a v1 blocker; the no-fabrication grounding is P0.)

---

## Cache + Cost Architecture (the structural win)

Cost is **per-call-minute** — linear by default, not zero-marginal SaaS. Two levers bend
it, both designed into v1 even though the cache starts cold:

1. **Callback elimination** (biggest per-job cut, >50%). Detect "press N for a callback,"
   take it, hang up to stop the meter, resume on inbound callback. (Full inbound routing
   is P1; design the state machine for it now.)
2. **Caching** (the moat). Store answers keyed by `(business, normalized_question)` with a
   **per-field TTL** (a price expires faster than "do you service Hondas"). 50 users want a
   brake quote in one metro → ~1 call, not 50. `CACHE_CHECK` + the keyed store are **P0
   plumbing** so the benefit compounds instead of being a retrofit.

Supporting levers: cheap model/TTS during hold (only need "human back yet?" detection);
route the stack by task (mechanical bulk = cheap model, reasoning moments = expensive);
per-job minute budget + hold-abandon threshold + concurrency cap to cap downside.

**Freshness is mandatory.** A stale quote is worse than no quote. Serve within TTL,
re-verify with a live call past it — never serve stale.

---

## Priorities

**P0 (build in v1):** three-part input + request object · pre-call brief · call state
machine with terminal-state logging · the hard rule · transcript capture per call ·
ranked results table + per-call transcript cards · async completion notification ·
CACHE_CHECK + keyed answer store (even if cold) · concurrency cap.

**P1 (fast follow):** callback elimination (needs inbound routing) · cheap-stack-during-hold
+ abandon threshold · per-vertical hint packs · live in-progress status chips · "retry the
ones that didn't answer" · caveat/confidence extraction.

**P2 (design so these stay easy, don't build):** number auto-discovery (v2 — keep `targets`
a plain input; engine never assumes its origin) · booking/transacting tier (+ verification)
· real-time "patch me in" handoff · SMS-native interface.

---

## Non-Goals (explicit — do NOT build in v1)

- No transacting (no booking/canceling/negotiating/committing the user). Read-only info only.
- No identity-verification flow (v1 targets prospective-customer questions that don't need it).
- No sensitive-data storage (no SSN/DOB/account/payment). Keeps v1 from also being a security project.
- No mid-call user interruption (blocked → close + report; the whole flow stays async).
- No number discovery (user supplies numbers).
- No billing (free prototype; monetize after completion rate is proven).
- No mobile app (web only).

---

## Success Metric

**≥70% of reachable businesses return usable info.** Every design tradeoff serves this
number and the trust that backs it (transcripts).

---

## Working Conventions

- **Plan first.** Non-trivial change → write the plan (files, approach, tests) before editing.
- **Keep the engine generic.** No vertical `if` branches in orchestration/agent code.
  Vertical specifics live in data (hint packs), never logic.
- **Incremental build-and-test.** Small verifiable steps; new behavior ships with a test.
- **Async everywhere** on the backend. Calls are long-running I/O — never block the loop.
- **Type everything.** Pydantic v2 + full hints; `mypy` clean.
- **Prompts are code** — versioned files in `prompts/`, never inline. Each ships with an
  adversarial test set (interruptions, silence, rushed reps, IVR trees, contradictions, refusals).
- **Secrets** via env only. **No sensitive PII stored, by design** — enforce at the model level.

---

## Acceptance Criteria (must pass)

- Valid request, 1+ reachable targets → each call returns a terminal state; job shows a
  ranked table + a transcript per call.
- Human answers → agent discloses it's an AI assistant, asks, extracts return fields.
- Ask missing needed context → user is prompted for missing fields **before** any call.
- Business asks for a fact not in context → agent marks unknown, never fabricates
  (negative test: no invented facts in any transcript).
- vm/no-answer/busy → `COULDNT_REACH`, no message left, job continues.
- Refusal to quote by phone → `REFUSED` with reason, shown as an outcome not an error.
- User closes the tab → still gets a completion notification.
- N > cap targets → no more than cap calls run concurrently.
- Fresh cached answer within TTL → served with no call placed.
- Cached answer past TTL → re-verified with a call, not served stale.
- (P1) IVR offers callback → outbound ends (meter stops), job resumes on inbound callback.

---

## What NOT to do

- Do **not** build STT/TTS/turn-taking from scratch. Buy the pipeline.
- Do **not** put vertical logic in code. Hint packs are data.
- Do **not** let the agent fabricate a user fact or serve an ungrounded return value.
- Do **not** transact or commit the user to anything in v1.
- Do **not** store sensitive PII.
- Do **not** serve a cached answer past its TTL.
- Do **not** leave voicemails on COULDNT_REACH.
- Do **not** ping the user mid-call.