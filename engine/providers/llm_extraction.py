"""Real structured-output extraction provider (OpenAI / Anthropic).

Not the default provider and not exercised by CI beyond the opt-in
`@pytest.mark.integration` test — `engine/providers/mock.py` is what runs
in `pytest` and the CLI demo. This is a genuine drop-in implementation
selected via `settings.llm_provider`, not a TODO stub.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from engine.models import TranscriptTurn, Vertical
from engine.prompts import load_prompt


class LLMExtractionProvider:
    def __init__(
        self, provider: Literal["openai", "anthropic"], api_key: str, model: str | None = None
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model or ("gpt-4o" if provider == "openai" else "claude-sonnet-5")

    async def extract(self, vertical: Vertical, transcript: list[TranscriptTurn]) -> BaseModel:
        system_prompt = load_prompt(vertical.id, "extraction_system")
        transcript_text = "\n".join(f"{turn.speaker}: {turn.text}" for turn in transcript)

        if self.provider == "openai":
            return await self._extract_openai(vertical, system_prompt, transcript_text)
        return await self._extract_anthropic(vertical, system_prompt, transcript_text)

    async def _extract_openai(
        self, vertical: Vertical, system_prompt: str, transcript_text: str
    ) -> BaseModel:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)
        completion = await client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript_text},
            ],
            response_format=vertical.extraction_schema,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI structured-output extraction returned no parsed result")
        return parsed

    async def _extract_anthropic(
        self, vertical: Vertical, system_prompt: str, transcript_text: str
    ) -> BaseModel:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": transcript_text}],
            tools=[
                {
                    "name": "record_extraction",
                    "description": "Record the extracted fields.",
                    "input_schema": vertical.extraction_schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "record_extraction"},
        )
        tool_use = next(block for block in response.content if block.type == "tool_use")
        return vertical.extraction_schema.model_validate(tool_use.input)
