from __future__ import annotations

from engine.cache import InMemoryCacheStore
from engine.call_loop import run_call
from engine.models import Request, TerminalState
from engine.providers.mock import MockExtractionProvider, MockVoicePlatformProvider


async def test_fact_not_in_context_is_marked_unknown_not_fabricated() -> None:
    """CLAUDE.md's literal acceptance criterion, proven end-to-end (not just
    at the ground_field unit level): the +15550000001 mock scenario has the
    shop ask for the VIN, which isn't in the context bundle, and the scripted
    agent turn declines it rather than inventing one — no VIN is ever spoken
    on the call. Requesting "warranty_length" as a return_field (also never
    mentioned) must come back unknown, never a fabricated value, while a
    field that genuinely was stated (price) still grounds normally.

    (return_field is "warranty_length", not "vin" — the word "VIN" itself
    appears in the shop's question and the agent's decline, which would
    trip MockExtractionProvider's naive keyword-substring heuristic into a
    false match; that heuristic is explicitly demo-only/never
    load-bearing, so the test targets a field with no such collision.)
    """
    request = Request(
        ask="quote for front brake pad replacement",
        return_fields=["price", "warranty_length"],
        context={"car": "2018 Honda Civic", "mileage": 82000, "symptom": "squealing"},
        targets=["+15550000001"],
    )
    platform = MockVoicePlatformProvider()
    extraction = MockExtractionProvider()
    cache = InMemoryCacheStore()

    result = await run_call(request, "+15550000001", platform, extraction, cache)

    assert result.terminal_state is TerminalState.GOT_INFO
    assert result.fields["warranty_length"].value is None
    assert result.fields["warranty_length"].source_span is None
    assert result.fields["warranty_length"].reason is not None

    assert result.fields["price"].value == 220.0
    assert result.fields["price"].source_span is not None
