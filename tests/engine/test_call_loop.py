from __future__ import annotations

from engine.call_loop import run_call
from engine.extraction_schema import build_extraction_schema
from engine.models import AnswerType, CallOutcome, Question, Target, Vertical
from engine.providers.mock import MockDialogueLLMProvider


class ScriptedSession:
    def __init__(self, answers: dict[str, str]) -> None:
        self._answers = answers
        self.said: list[str] = []

    async def say(self, text: str) -> None:
        self.said.append(text)

    async def listen(self, *, question_id: str, is_clarify: bool = False) -> str:
        key = f"{question_id}__clarify" if is_clarify else question_id
        return self._answers[key]


class ScriptedTelephony:
    def __init__(self, answers: dict[str, str]) -> None:
        self._answers = answers

    async def start_call(self, target: Target) -> ScriptedSession:
        return ScriptedSession(self._answers)

    async def end_call(self, session: ScriptedSession) -> None:
        return None


TARGET = Target(id="x", name="X", phone_number="+15555550000")


async def test_disclosure_is_always_the_first_turn(synthetic_vertical: Vertical) -> None:
    telephony = ScriptedTelephony({"favorite_color": "Blue.", "score": "Nine."})
    turns, outcome = await run_call(synthetic_vertical, TARGET, telephony, MockDialogueLLMProvider())
    assert turns[0].speaker == "agent"
    assert turns[0].text == synthetic_vertical.disclosure_script
    assert outcome is CallOutcome.COMPLETED


async def test_clear_answer_produces_exactly_one_ask_answer_pair(synthetic_vertical: Vertical) -> None:
    telephony = ScriptedTelephony({"favorite_color": "Blue.", "score": "Nine."})
    turns, _ = await run_call(synthetic_vertical, TARGET, telephony, MockDialogueLLMProvider())
    for question in synthetic_vertical.question_set:
        q_turns = [t for t in turns if t.question_id == question.id]
        assert len(q_turns) == 2
        assert not any(t.is_clarify for t in q_turns)


async def test_ambiguous_answer_triggers_exactly_one_clarify(synthetic_vertical: Vertical) -> None:
    telephony = ScriptedTelephony(
        {
            "favorite_color": "around blue-ish, depends on the light",
            "favorite_color__clarify": "Blue.",
            "score": "Nine.",
        }
    )
    turns, _ = await run_call(synthetic_vertical, TARGET, telephony, MockDialogueLLMProvider())
    color_turns = [t for t in turns if t.question_id == "favorite_color"]
    # ask, hedged answer, clarify-ask, clarify-answer — never more than one clarify round.
    assert len(color_turns) == 4
    assert sum(1 for t in color_turns if t.is_clarify) == 2


async def test_refused_answer_moves_on_without_clarifying(synthetic_vertical: Vertical) -> None:
    telephony = ScriptedTelephony(
        {"favorite_color": "I'm not able to share that over the phone.", "score": "Nine."}
    )
    turns, _ = await run_call(synthetic_vertical, TARGET, telephony, MockDialogueLLMProvider())
    color_turns = [t for t in turns if t.question_id == "favorite_color"]
    assert len(color_turns) == 2
    assert not any(t.is_clarify for t in color_turns)


async def test_loop_is_vertical_agnostic() -> None:
    """A completely different Vertical drives the exact same loop shape —
    call_loop.py contains no `if vertical.id ==` branch to test against."""
    questions = [Question(id="q1", prompt="Q1?", answer_type=AnswerType.STR, clarify_prompt="Clarify Q1?")]
    other_vertical = Vertical(
        id="another_vertical",
        goal="Other goal.",
        disclosure_script="Other disclosure.",
        question_set=questions,
        extraction_schema=build_extraction_schema("another_vertical", questions),
        result_mode="single",
    )
    telephony = ScriptedTelephony({"q1": "Answer."})
    turns, outcome = await run_call(other_vertical, TARGET, telephony, MockDialogueLLMProvider())
    assert turns[0].text == "Other disclosure."
    assert outcome is CallOutcome.COMPLETED
