"""The rental vertical: config only, zero engine changes.

Adding a question here automatically produces a corresponding
`ExtractedField[T]` on the generated extraction schema — see
`engine.extraction_schema.build_extraction_schema`.
"""

from __future__ import annotations

from engine.extraction_schema import build_extraction_schema
from engine.models import AnswerType, Question, Vertical
from engine.prompts import load_prompt

QUESTION_SET: list[Question] = [
    Question(
        id="monthly_rent",
        prompt="What's the monthly rent for a one-bedroom unit?",
        answer_type=AnswerType.FLOAT,
        required=True,
        clarify_prompt=(
            "Just to confirm — what's the exact monthly rent figure, or the range if it "
            "varies by unit?"
        ),
        description="Monthly rent in USD for a 1BR unit.",
    ),
    Question(
        id="available_date",
        prompt="When is the unit available to move in?",
        answer_type=AnswerType.DATE,
        required=True,
        clarify_prompt="Could you give me an approximate move-in date, even a rough month is fine?",
        description="Earliest move-in / availability date.",
    ),
    Question(
        id="pet_policy",
        prompt="What's your pet policy — are cats and dogs allowed?",
        answer_type=AnswerType.STR,
        required=True,
        clarify_prompt=(
            "To be clear, are pets allowed at all, and are there any restrictions like "
            "breed or weight limits?"
        ),
        description="Free-text summary of pet policy including restrictions/fees.",
    ),
    Question(
        id="security_deposit",
        prompt="How much is the security deposit?",
        answer_type=AnswerType.FLOAT,
        required=True,
        clarify_prompt="Roughly how much should I expect for the security deposit?",
        description="Security deposit amount in USD.",
    ),
    Question(
        id="application_fee",
        prompt="Is there an application fee, and if so how much?",
        answer_type=AnswerType.FLOAT,
        required=False,
        clarify_prompt="Just so I have a number — what's the application fee?",
        description="Non-refundable application fee in USD, 0 if none.",
    ),
    Question(
        id="utilities_included",
        prompt="Are any utilities included in the rent?",
        answer_type=AnswerType.ENUM,
        required=False,
        enum_values=["all_included", "some_included", "none_included", "unknown"],
        clarify_prompt=(
            "Which utilities specifically are included, if any — water, gas, trash, electric?"
        ),
        description="Category describing which utilities are covered by rent.",
    ),
]


def build_rental_vertical() -> Vertical:
    return Vertical(
        id="rental",
        goal=load_prompt("rental", "goal"),
        disclosure_script=load_prompt("rental", "disclosure"),
        question_set=QUESTION_SET,
        extraction_schema=build_extraction_schema("rental", QUESTION_SET),
        result_mode="compare",
    )
