"""The vertical-agnostic per-call state machine.

Every string this loop speaks comes from `vertical.disclosure_script` or a
`Question`'s own `prompt`/`clarify_prompt`. There is no `if vertical.id ==`
branch anywhere in this file, and there must never be one — that branch is
the failure of the whole "engine vs vertical" bet (see CLAUDE.md).
"""

from __future__ import annotations

import itertools

from engine.models import AnswerClassification, CallOutcome, Target, TranscriptTurn, Vertical
from engine.providers.base import DialogueLLMProvider, TelephonyProvider


def _agent_turn(
    turn_id: int, text: str, *, question_id: str | None = None, is_clarify: bool = False
) -> TranscriptTurn:
    return TranscriptTurn(
        turn_id=turn_id, speaker="agent", text=text, question_id=question_id, is_clarify=is_clarify
    )


def _human_turn(
    turn_id: int, text: str, *, question_id: str | None = None, is_clarify: bool = False
) -> TranscriptTurn:
    return TranscriptTurn(
        turn_id=turn_id, speaker="human", text=text, question_id=question_id, is_clarify=is_clarify
    )


async def run_call(
    vertical: Vertical,
    target: Target,
    telephony: TelephonyProvider,
    dialogue: DialogueLLMProvider,
) -> tuple[list[TranscriptTurn], CallOutcome]:
    session = await telephony.start_call(target)
    turns: list[TranscriptTurn] = []
    counter = itertools.count()

    await session.say(vertical.disclosure_script)
    turns.append(_agent_turn(next(counter), vertical.disclosure_script))

    for question in vertical.question_set:
        await session.say(question.prompt)
        turns.append(_agent_turn(next(counter), question.prompt, question_id=question.id))

        answer = await session.listen(question_id=question.id, is_clarify=False)
        turns.append(_human_turn(next(counter), answer, question_id=question.id))

        classification = await dialogue.classify_answer(question, answer, turns)

        if classification is AnswerClassification.AMBIGUOUS and question.clarify_prompt:
            await session.say(question.clarify_prompt)
            turns.append(
                _agent_turn(
                    next(counter), question.clarify_prompt, question_id=question.id, is_clarify=True
                )
            )
            follow_up = await session.listen(question_id=question.id, is_clarify=True)
            turns.append(
                _human_turn(next(counter), follow_up, question_id=question.id, is_clarify=True)
            )
            # Exactly ONE follow-up, regardless of how the follow-up itself
            # would classify — then move on. Never loop on ambiguity.

        # CLEAR and REFUSED both fall through here with no further action.

    await telephony.end_call(session)
    return turns, CallOutcome.COMPLETED
