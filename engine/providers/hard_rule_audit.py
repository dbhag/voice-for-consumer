"""Post-hoc hard-rule audit — deliberately NOT part of the live call loop or
`ProviderBundle`. `ground_field` (engine/extraction.py) already guarantees
every *extracted return_field value* has a source span; it says nothing
about a fact the agent mentions in passing that never became a return
field and so never went through `ground_field` at all. This is the check
for that gap: given a completed call's transcript + context bundle, ask
whether the agent stated any fact outside the context bundle.

Used by `app.cli report` (a post-hoc report over a persisted job), not by
`engine.orchestrator.run_job` — auditing happens after the call, not during
it. One bought LLM call (OpenAI/Anthropic), same pattern as
`engine/providers/llm_extraction.py`.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

from engine.models import TranscriptTurn
from engine.prompts import load_prompt


class AuditResult(BaseModel):
    clean: bool
    violation_detail: str | None = None


class HardRuleAuditProvider(Protocol):
    async def audit(
        self, transcript: list[TranscriptTurn], context: dict[str, object]
    ) -> AuditResult: ...


class LLMHardRuleAuditProvider:
    def __init__(
        self, provider: Literal["openai", "anthropic"], api_key: str, model: str | None = None
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model or ("gpt-4o" if provider == "openai" else "claude-sonnet-5")

    async def audit(
        self, transcript: list[TranscriptTurn], context: dict[str, object]
    ) -> AuditResult:
        system_prompt = load_prompt("audit", "system")
        transcript_text = "\n".join(f"{turn.speaker}: {turn.text}" for turn in transcript)
        user_prompt = f"context bundle: {context}\n\ntranscript:\n{transcript_text}"

        if self.provider == "openai":
            return await self._audit_openai(system_prompt, user_prompt)
        return await self._audit_anthropic(system_prompt, user_prompt)

    async def _audit_openai(self, system_prompt: str, user_prompt: str) -> AuditResult:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)
        completion = await client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=AuditResult,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI structured-output audit returned no parsed result")
        return parsed

    async def _audit_anthropic(self, system_prompt: str, user_prompt: str) -> AuditResult:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[
                {
                    "name": "record_audit",
                    "description": "Record the hard-rule audit result.",
                    "input_schema": AuditResult.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "record_audit"},
        )
        tool_use = next(block for block in response.content if block.type == "tool_use")
        return AuditResult.model_validate(tool_use.input)
