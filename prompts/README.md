# Prompts

Prompts are code: versioned files, never inlined as Python string literals.

## Layout

```
prompts/<topic>/<version>/<name>.txt
```

Topics are generic engine concerns — `dialogue`, `extraction`, `pre_call_brief` —
never a vertical name. Vertical differences live in `hint_packs/` (plain data),
not here.

## Versioning

- Never edit a prompt file in place once it has been used in a real call —
  add a new `v2/`, `v3/`, ... directory instead, so past call results stay
  traceable to the exact prompt text that produced them.
- `engine.prompts.load_prompt(topic, name, version="v1")` reads these files.

## Files

- `dialogue/v1/system.txt` — the brief handed to the bought voice platform
  at CONVERSE time: disclosure + primary question + context bundle +
  the hard rule (never fabricate a fact not in context). This is the
  highest-leverage prompt in the product — it's what makes the pre-call
  brief actually front-load context into the live call.
- `extraction/v1/system.txt` — system prompt for the real structured-output
  extraction call (`engine/providers/llm_extraction.py`).
- `pre_call_brief/v1/system.txt` — system prompt for the real pre-call-brief
  LLM call (`engine/providers/llm_pre_call_brief.py`).

There is no `classify_answer` prompt: CLASSIFY_ANSWER (human / IVR / hold /
voicemail-no-answer-busy) is telephony-level call state reported by the
bought voice platform, not something we classify with our own LLM call.
