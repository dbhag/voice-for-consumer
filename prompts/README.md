# Prompts

Prompts are code: versioned files, never inlined as Python string literals.

## Layout

```
prompts/<vertical_id>/<version>/<name>.txt
```

## Versioning

- Never edit a prompt file in place once it has been used in a real call —
  add a new `v2/`, `v3/`, ... directory instead, so past call results stay
  traceable to the exact prompt text that produced them.
- `engine.prompts.load_prompt(vertical_id, name, version="v1")` reads these
  files; verticals default to their current version.

## Files per vertical

- `disclosure.txt` — the legally-required AI-disclosure opening line.
- `goal.txt` — natural-language objective handed to the dialogue agent.
- `dialogue_system.txt` — system prompt for the real dialogue LLM (not used
  by the mock providers in this pass).
- `classify_answer.txt` — prompt for the real answer-classification LLM call
  (not used by the mock providers in this pass).
- `extraction_system.txt` — system prompt for the real structured-output
  extraction call (`engine/providers/llm_extraction.py`).
