"""Real pre-call-brief LLM call — the highest-leverage P0 step per CLAUDE.md,
one bought LLM call (OpenAI/Anthropic), independent of the voice platform.

Not the default provider and not exercised by CI beyond the opt-in
`@pytest.mark.integration` test (contrast with `engine/providers/mock.py`,
whose deterministic brief is demo-only).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from engine.models import MissingContext, PreCallBrief, Request
from engine.prompts import load_prompt


class _BriefResult(BaseModel):
    primary_question: str
    return_fields: list[str]
    likely_follow_ups: list[str]
    missing_context: list[MissingContext]
    dropped_context_keys: list[str]


class LLMPreCallBriefProvider:
    def __init__(
        self, provider: Literal["openai", "anthropic"], api_key: str, model: str | None = None
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model or ("gpt-4o" if provider == "openai" else "claude-sonnet-5")

    async def build_brief(self, request: Request, hint_pack: dict[str, Any] | None) -> PreCallBrief:
        system_prompt = load_prompt("pre_call_brief", "system")
        user_prompt = (
            f"ask: {request.ask}\n"
            f"return_fields: {request.return_fields}\n"
            f"context: {request.context}\n"
            f"hint_pack: {hint_pack}"
        )

        if self.provider == "openai":
            raw = await self._build_openai(system_prompt, user_prompt)
        else:
            raw = await self._build_anthropic(system_prompt, user_prompt)

        return PreCallBrief(
            primary_question=raw.primary_question,
            return_fields=raw.return_fields,
            likely_follow_ups=raw.likely_follow_ups,
            missing_context=raw.missing_context,
            dropped_context_keys=raw.dropped_context_keys,
        )

    async def _build_openai(self, system_prompt: str, user_prompt: str) -> _BriefResult:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)
        completion = await client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=_BriefResult,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI structured-output pre-call brief returned no parsed result")
        return parsed

    async def _build_anthropic(self, system_prompt: str, user_prompt: str) -> _BriefResult:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[
                {
                    "name": "record_brief",
                    "description": "Record the pre-call brief.",
                    "input_schema": _BriefResult.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "record_brief"},
        )
        tool_use = next(block for block in response.content if block.type == "tool_use")
        return _BriefResult.model_validate(tool_use.input)
