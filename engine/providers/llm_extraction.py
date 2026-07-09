"""Real structured-output extraction (OpenAI / Anthropic) — one bought LLM
call per CLAUDE.md's Stack table, independent of the voice platform.

Handles arbitrary `return_fields` generically: the LLM reads the field
names + transcript and reasons about grounding itself, so no per-field
code branches exist here (contrast with `engine/providers/mock.py`, whose
keyword heuristics are demo-only and never load-bearing in production).

Not the default provider and not exercised by CI beyond the opt-in
`@pytest.mark.integration` test.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from engine.extraction import ground_field
from engine.models import FieldResult, TranscriptTurn
from engine.prompts import load_prompt


class _FieldExtraction(BaseModel):
    value: str | float | bool | None
    source_span: str | None
    reason: str | None = None


class _ExtractionResult(BaseModel):
    fields: dict[str, _FieldExtraction]


class LLMExtractionProvider:
    def __init__(
        self, provider: Literal["openai", "anthropic"], api_key: str, model: str | None = None
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model or ("gpt-4o" if provider == "openai" else "claude-sonnet-5")

    async def extract(
        self, return_fields: list[str], transcript: list[TranscriptTurn]
    ) -> dict[str, FieldResult]:
        system_prompt = load_prompt("extraction", "system")
        transcript_text = "\n".join(f"{turn.speaker}: {turn.text}" for turn in transcript)
        user_prompt = f"return_fields: {return_fields}\n\ntranscript:\n{transcript_text}"

        if self.provider == "openai":
            raw = await self._extract_openai(system_prompt, user_prompt)
        else:
            raw = await self._extract_anthropic(system_prompt, user_prompt)

        return {
            field: ground_field(f.value, f.source_span, reason=f.reason)
            for field, f in raw.fields.items()
        }

    async def _extract_openai(self, system_prompt: str, user_prompt: str) -> _ExtractionResult:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)
        completion = await client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=_ExtractionResult,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI structured-output extraction returned no parsed result")
        return parsed

    async def _extract_anthropic(self, system_prompt: str, user_prompt: str) -> _ExtractionResult:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[
                {
                    "name": "record_extraction",
                    "description": "Record the extracted fields.",
                    "input_schema": _ExtractionResult.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "record_extraction"},
        )
        tool_use = next(block for block in response.content if block.type == "tool_use")
        return _ExtractionResult.model_validate(tool_use.input)
