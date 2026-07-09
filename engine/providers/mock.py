"""Deterministic, offline providers used for local dev / CI / the CLI demo.

No network calls, no API keys required. These implement the same Protocols
(`engine.providers.base`) that a real Bland/Retell/Vapi-backed provider and a
real LLM pre-call-brief/extraction provider implement.

`MockExtractionProvider`'s keyword heuristics are demo-only and never
load-bearing in production — the real path is
`engine/providers/llm_extraction.py`. Every value still goes through
`ground_field`, so the hard rule holds even here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from engine.extraction import ground_field
from engine.models import (
    ClassifyAnswer,
    ConverseOutcome,
    FieldResult,
    HoldOutcome,
    MenuOutcome,
    PreCallBrief,
    Request,
    TranscriptTurn,
)
from engine.pre_call_brief import missing_context_fields


@dataclass
class _Scenario:
    classify: ClassifyAnswer
    menu_outcome: MenuOutcome | None = None
    hold_outcome: HoldOutcome | None = None
    converse_script: list[tuple[str, str]] | None = None
    refused: bool = False
    refusal_reason: str | None = None


# Canned scenarios keyed by phone number, covering every branch of the call
# state machine in CLAUDE.md — used by the CLI demo and exercised by tests.
SCENARIOS: dict[str, _Scenario] = {
    # Human answers, gives full info, and demonstrates the hard rule (agent
    # declines a fact — the VIN — that isn't in the context bundle).
    "+15550000001": _Scenario(
        classify=ClassifyAnswer.HUMAN,
        converse_script=[
            ("human", "Sure, let me check — do you have the VIN?"),
            (
                "agent",
                "I don't have the VIN on hand, sorry — is there anything else "
                "you can go off of?",
            ),
            (
                "human",
                "That's fine. For a 2018 Civic with squealing brakes it's $220 "
                "for parts and labor, mostly labor cost. Your earliest "
                "availability would be tomorrow morning.",
            ),
        ],
    ),
    # IVR -> hold -> human returns, but only answers part of what was asked.
    "+15550000002": _Scenario(
        classify=ClassifyAnswer.IVR,
        menu_outcome=MenuOutcome.HOLD,
        hold_outcome=HoldOutcome.HUMAN_RETURNED,
        converse_script=[
            (
                "human",
                "Thanks for holding. For a 2018 Civic with squealing brakes, "
                "that's $250, mostly labor cost, some parts too.",
            ),
        ],
    ),
    # IVR -> hold -> caller gives up before a human returns.
    "+15550000003": _Scenario(
        classify=ClassifyAnswer.IVR,
        menu_outcome=MenuOutcome.HOLD,
        hold_outcome=HoldOutcome.ABANDONED,
    ),
    # Voicemail / no answer / busy — no message is left.
    "+15550000004": _Scenario(classify=ClassifyAnswer.VM_NO_ANSWER_BUSY),
    # Human answers but the shop won't quote by phone.
    "+15550000005": _Scenario(
        classify=ClassifyAnswer.HUMAN,
        converse_script=[
            (
                "human",
                "I'm sorry, we don't give quotes over the phone — you'd need "
                "to bring it in.",
            ),
        ],
        refused=True,
        refusal_reason="business does not quote by phone",
    ),
    # IVR offers a callback; we take it and hang up to stop the meter.
    "+15550000006": _Scenario(
        classify=ClassifyAnswer.IVR,
        menu_outcome=MenuOutcome.CALLBACK_OFFERED,
    ),
}

DEFAULT_SCENARIO = _Scenario(
    classify=ClassifyAnswer.HUMAN,
    converse_script=[("human", "It's $150.")],
)


class MockVoiceCallSession:
    def __init__(self, scenario: _Scenario) -> None:
        self._scenario = scenario
        self.callback_requested = False
        self.hung_up = False

    async def classify(self) -> ClassifyAnswer:
        return self._scenario.classify

    async def navigate_menu(self) -> MenuOutcome:
        assert self._scenario.menu_outcome is not None
        return self._scenario.menu_outcome

    async def wait_on_hold(self) -> HoldOutcome:
        assert self._scenario.hold_outcome is not None
        return self._scenario.hold_outcome

    async def request_callback(self) -> None:
        self.callback_requested = True

    async def converse(
        self, disclosure: str, primary_question: str, context: dict[str, object]
    ) -> ConverseOutcome:
        turns = [
            TranscriptTurn(turn_id=0, speaker="agent", text=disclosure),
            TranscriptTurn(turn_id=1, speaker="agent", text=primary_question),
        ]
        for i, (speaker, text) in enumerate(self._scenario.converse_script or [], start=2):
            turns.append(TranscriptTurn(turn_id=i, speaker=speaker, text=text))
        return ConverseOutcome(
            transcript=turns,
            refused=self._scenario.refused,
            refusal_reason=self._scenario.refusal_reason,
        )

    async def hangup(self) -> None:
        self.hung_up = True


class MockVoicePlatformProvider:
    async def start_call(self, phone_number: str) -> MockVoiceCallSession:
        return MockVoiceCallSession(SCENARIOS.get(phone_number, DEFAULT_SCENARIO))


class MockPreCallBriefProvider:
    async def build_brief(
        self, request: Request, hint_pack: dict[str, Any] | None
    ) -> PreCallBrief:
        likely_follow_ups = (
            [f["prompt"] for f in hint_pack.get("likely_follow_up_fields", [])]
            if hint_pack
            else []
        )
        return PreCallBrief(
            primary_question=request.ask,
            return_fields=request.return_fields,
            likely_follow_ups=likely_follow_ups,
            missing_context=missing_context_fields(request.context, hint_pack),
        )


_DOLLAR_RE = re.compile(r"\$[\d,]+(?:\.\d+)?")
_MONEY_FIELD_HINTS = ("price", "cost", "fee", "deposit", "quote")


def _keyword_for(field_name: str) -> str:
    return field_name.split("_")[0].lower()


class MockExtractionProvider:
    async def extract(
        self, return_fields: list[str], transcript: list[TranscriptTurn]
    ) -> dict[str, FieldResult]:
        human_turns = [t for t in transcript if t.speaker == "human"]
        full_text = " ".join(t.text.lower() for t in transcript)
        return {
            field_name: self._extract_one(field_name, human_turns, full_text)
            for field_name in return_fields
        }

    def _extract_one(
        self, field_name: str, human_turns: list[TranscriptTurn], full_text: str
    ) -> FieldResult:
        if not human_turns:
            return ground_field(None, None, reason="no human turns in transcript")

        if any(hint in field_name for hint in _MONEY_FIELD_HINTS):
            for turn in human_turns:
                match = _DOLLAR_RE.search(turn.text)
                if match:
                    amount = float(match.group().replace("$", "").replace(",", ""))
                    return ground_field(amount, turn.text)
            return ground_field(None, None, reason="no dollar amount mentioned")

        if _keyword_for(field_name) not in full_text:
            return ground_field(None, None, reason="not mentioned on the call")

        return ground_field(human_turns[-1].text, human_turns[-1].text)
