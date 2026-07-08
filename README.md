# Proxy

A consumer's outbound voice agent. Proxy calls businesses **on the user's behalf** —
the opposite of Vapi/Retell/Bland, which arm the business answering the phone —
runs the conversation, and returns structured, confidence-scored results.

The first configured use case is calling apartment leasing offices to run a
standardized rental-screening interview and build a comparison across properties.
It's a demo of the general pattern, not the product: the engine is vertical-agnostic,
and rental is config (`verticals/rental/`), not hardcoded logic. See
[CLAUDE.md](CLAUDE.md) for the full design spec and non-negotiable principles
(confidence-gated extraction, prompt robustness, engine/vertical separation).

## Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Commands

```bash
uvicorn app.main:app --reload                                       # backend API
python -m app.agent.worker                                           # voice agent worker (Pipecat) — not implemented yet
python -m app.cli run --vertical rental --targets examples/rental_targets.json   # local dev run, mock providers

pytest                          # unit + extraction tests
pytest tests/prompts -v         # adversarial prompt suite
pytest -m integration           # end-to-end with mocked STT/TTS

cd dashboard && npm run dev     # comparison + drill-down dashboard — not built yet

mypy app/ engine/ verticals/ && ruff check app/ engine/ verticals/
```

## Build status

Bootstrapped in phases per the plan in `CLAUDE.md`'s "incremental build-and-test"
convention. Current phase: **mocked end-to-end loop** — `app.cli run` executes the
full dialogue + confidence-gated extraction loop against deterministic mock
telephony/dialogue/extraction providers (no API keys, no network). Deferred: real
Pipecat/Twilio/Deepgram wiring, live DB/queue persistence, dashboard.
