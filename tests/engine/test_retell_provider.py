from __future__ import annotations

import httpx
import pytest

from engine.models import ClassifyAnswer, Request
from engine.providers.retell import (
    RetellVoiceCallSession,
    RetellVoicePlatformProvider,
    build_dynamic_variables,
    render_context_summary,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.retellai.com"
    )


def _sample_request(**overrides) -> Request:
    base = dict(
        ask="quote for front brake pad replacement",
        return_fields=["price", "parts_vs_labor"],
        context={"car": "2018 Honda Civic", "mileage": 82000},
        targets=["+15550000001"],
    )
    base.update(overrides)
    return Request(**base)


# ---------------------------------------------------------------------------
# Dynamic variables / context summary — deterministic formatting
# ---------------------------------------------------------------------------


def test_context_summary_is_sorted_and_not_json() -> None:
    summary = render_context_summary({"mileage": 82000, "car": "2018 Honda Civic"})

    assert summary == "Car: 2018 Honda Civic. Mileage: 82000."
    assert "{" not in summary


def test_context_summary_is_deterministic_regardless_of_dict_insertion_order() -> None:
    a = render_context_summary({"symptom": "squealing", "car": "2018 Civic"})
    b = render_context_summary({"car": "2018 Civic", "symptom": "squealing"})

    assert a == b


def test_build_dynamic_variables_uses_hint_pack_labels() -> None:
    request = _sample_request()
    hint_pack = {
        "field_labels": {"price": "the price", "parts_vs_labor": "parts vs labor cost split"},
    }

    variables = build_dynamic_variables(request, hint_pack)

    assert variables["ask"] == request.ask
    assert variables["return_fields"] == "the price, parts vs labor cost split"
    assert variables["context_summary"] == "Car: 2018 Honda Civic. Mileage: 82000."
    assert "opening_purpose" not in variables
    assert all(isinstance(v, str) for v in variables.values())


def test_build_dynamic_variables_falls_back_without_a_hint_pack() -> None:
    request = _sample_request(return_fields=["earliest_availability"])

    variables = build_dynamic_variables(request, None)

    assert variables["ask"] == request.ask
    assert variables["return_fields"] == "earliest availability"
    assert "opening_purpose" not in variables


# ---------------------------------------------------------------------------
# start_call -> classify -> converse, against a stubbed Retell HTTP layer
# ---------------------------------------------------------------------------


def _create_call_response(call_id: str = "call_123") -> httpx.Response:
    return httpx.Response(201, json={"call_id": call_id})


def _ended_call_record(
    *,
    disconnection_reason: str = "user_hangup",
    in_voicemail: bool = False,
    transcript_object=None,
    custom_analysis_data=None,
    call_cost=None,
) -> dict:
    call_analysis = {
        "in_voicemail": in_voicemail,
        "custom_analysis_data": custom_analysis_data or {},
    }
    if call_cost is not None:
        call_analysis["call_cost"] = call_cost
    return {
        "call_id": "call_123",
        "call_status": "ended",
        "disconnection_reason": disconnection_reason,
        "call_analysis": call_analysis,
        "transcript_object": transcript_object or [],
    }


async def test_happy_path_places_call_polls_until_ended_and_translates_transcript() -> None:
    poll_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        if request.url.path == "/v2/get-call/call_123":
            poll_count["n"] += 1
            if poll_count["n"] < 3:
                return httpx.Response(200, json={"call_id": "call_123", "call_status": "ongoing"})
            return httpx.Response(
                200,
                json=_ended_call_record(
                    transcript_object=[
                        {"role": "agent", "content": "Hi, quick question."},
                        {"role": "user", "content": "Sure, go ahead."},
                    ]
                ),
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provider = RetellVoicePlatformProvider(
        api_key="test-key",
        from_number="+15551110000",
        agent_id="agent_abc",
        http_client=_client(handler),
        poll_interval_seconds=0.001,
        poll_timeout_seconds=5,
    )
    request = _sample_request()

    session = await provider.start_call(request, "+15550000001")
    classification = await session.classify()
    outcome = await session.converse("disclosure", request.ask, request.context)
    await session.hangup()

    assert classification is ClassifyAnswer.HUMAN
    assert poll_count["n"] == 3
    assert len(outcome.transcript) == 2
    assert outcome.transcript[0].speaker == "agent"
    assert outcome.transcript[1].speaker == "human"
    assert outcome.refused is False


async def test_voicemail_disconnection_reason_classifies_as_vm_no_answer_busy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(
            200, json=_ended_call_record(disconnection_reason="voicemail_reached")
        )

    provider = RetellVoicePlatformProvider(
        api_key="k", from_number="+15551110000", http_client=_client(handler)
    )
    session = await provider.start_call(_sample_request(), "+15550000001")

    assert await session.classify() is ClassifyAnswer.VM_NO_ANSWER_BUSY


@pytest.mark.parametrize(
    "reason", ["dial_failed", "invalid_destination", "sip_routing_error", "registered_call_timeout"]
)
async def test_other_no_connect_reasons_collapse_onto_vm_no_answer_busy(reason: str) -> None:
    """Documents the lossy mapping: Retell distinguishes many more failure
    modes than engine.models.ReachFailure has room for — all of them land on
    the same bucket as a real voicemail/busy/no-answer, which is a real loss
    of information, not a clean 1:1 mapping.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(200, json=_ended_call_record(disconnection_reason=reason))

    provider = RetellVoicePlatformProvider(
        api_key="k", from_number="+15551110000", http_client=_client(handler)
    )
    session = await provider.start_call(_sample_request(), "+15550000001")

    assert await session.classify() is ClassifyAnswer.VM_NO_ANSWER_BUSY


async def test_poll_timeout_is_treated_as_no_connect_not_an_infinite_hang() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(200, json={"call_id": "call_123", "call_status": "ongoing"})

    provider = RetellVoicePlatformProvider(
        api_key="k",
        from_number="+15551110000",
        http_client=_client(handler),
        poll_interval_seconds=0.001,
        poll_timeout_seconds=0.005,
    )
    session = await provider.start_call(_sample_request(), "+15550000001")

    assert await session.classify() is ClassifyAnswer.VM_NO_ANSWER_BUSY


async def test_waits_for_call_analysis_after_status_ends_before_returning() -> None:
    # Retell's docs: call_analysis populates *asynchronously* after
    # call_status hits "ended" (delivered via the call_analyzed webhook
    # once ready) — verified 2026-07-14 against docs.retellai.com, not
    # assumed. Reading call_analysis the instant call_status flips would
    # silently read an empty refused_to_quote/cost on real calls. This
    # reproduces that: status ends with no call_analysis for two polls,
    # then it shows up — classify()/converse() must reflect the version
    # with analysis, not the earlier bare one.
    poll_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        poll_count["n"] += 1
        if poll_count["n"] < 3:
            return httpx.Response(
                200, json={"call_id": "call_123", "call_status": "ended", "call_analysis": {}}
            )
        return httpx.Response(
            200,
            json=_ended_call_record(
                custom_analysis_data={
                    "refused_to_quote": True,
                    "refusal_reason": "business does not quote by phone",
                }
            ),
        )

    provider = RetellVoicePlatformProvider(
        api_key="k",
        from_number="+15551110000",
        http_client=_client(handler),
        poll_interval_seconds=0.001,
        poll_timeout_seconds=5,
        analysis_poll_timeout_seconds=5,
    )
    request = _sample_request()
    session = await provider.start_call(request, "+15550000001")
    await session.classify()

    outcome = await session.converse("disclosure", request.ask, request.context)

    assert poll_count["n"] == 3
    assert outcome.refused is True
    assert outcome.refusal_reason == "business does not quote by phone"


async def test_analysis_poll_timeout_proceeds_without_analysis_rather_than_hang() -> None:
    # call_status is "ended" from the first poll onward but call_analysis
    # never arrives — must give up after analysis_poll_timeout_seconds and
    # proceed with what it has, not block the job forever.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(
            200, json={"call_id": "call_123", "call_status": "ended", "call_analysis": {}}
        )

    provider = RetellVoicePlatformProvider(
        api_key="k",
        from_number="+15551110000",
        http_client=_client(handler),
        poll_interval_seconds=0.001,
        poll_timeout_seconds=5,
        analysis_poll_timeout_seconds=0.005,
    )
    request = _sample_request()
    session = await provider.start_call(request, "+15550000001")

    assert await session.classify() is ClassifyAnswer.HUMAN
    outcome = await session.converse("disclosure", request.ask, request.context)
    assert outcome.refused is False


async def test_refused_read_from_custom_analysis_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(
            200,
            json=_ended_call_record(
                custom_analysis_data={
                    "refused_to_quote": True,
                    "refusal_reason": "business does not quote by phone",
                }
            ),
        )

    provider = RetellVoicePlatformProvider(
        api_key="k", from_number="+15551110000", http_client=_client(handler)
    )
    request = _sample_request()
    session = await provider.start_call(request, "+15550000001")
    await session.classify()

    outcome = await session.converse("disclosure", request.ask, request.context)

    assert outcome.refused is True
    assert outcome.refusal_reason == "business does not quote by phone"


async def test_transfer_target_role_maps_to_human() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(
            200,
            json=_ended_call_record(
                transcript_object=[{"role": "transfer_target", "content": "This is the manager."}]
            ),
        )

    provider = RetellVoicePlatformProvider(
        api_key="k", from_number="+15551110000", http_client=_client(handler)
    )
    request = _sample_request()
    session = await provider.start_call(request, "+15550000001")
    await session.classify()

    outcome = await session.converse("disclosure", request.ask, request.context)

    assert outcome.transcript[0].speaker == "human"


# ---------------------------------------------------------------------------
# Cost — combined_cost and the per-product breakdown (cents -> USD)
# ---------------------------------------------------------------------------


async def test_cost_usd_and_breakdown_extracted_from_call_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(
            200,
            json=_ended_call_record(
                call_cost={
                    "combined_cost": 42,
                    "total_duration_seconds": 60,
                    "total_duration_unit_price": 0.7,
                    "product_costs": [
                        {"product": "retell_llm", "unit_price": 0.2, "cost": 12},
                        {"product": "elevenlabs_tts", "unit_price": 0.3, "cost": 18},
                        {"product": "twilio_telephony", "unit_price": 0.2, "cost": 12},
                    ],
                }
            ),
        )

    provider = RetellVoicePlatformProvider(
        api_key="k", from_number="+15551110000", http_client=_client(handler)
    )
    request = _sample_request()
    session = await provider.start_call(request, "+15550000001")
    await session.classify()

    outcome = await session.converse("disclosure", request.ask, request.context)

    assert outcome.cost_usd == pytest.approx(0.42)
    assert outcome.cost_breakdown_usd == {
        "retell_llm": pytest.approx(0.12),
        "elevenlabs_tts": pytest.approx(0.18),
        "twilio_telephony": pytest.approx(0.12),
    }


async def test_cost_breakdown_sums_repeated_product_entries() -> None:
    # is_transfer_leg_cost can split one product across two entries (a
    # transferred call has two legs) — both must land in the same total,
    # not overwrite each other.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(
            200,
            json=_ended_call_record(
                call_cost={
                    "combined_cost": 30,
                    "product_costs": [
                        {"product": "twilio_telephony", "cost": 10, "is_transfer_leg_cost": False},
                        {"product": "twilio_telephony", "cost": 20, "is_transfer_leg_cost": True},
                    ],
                }
            ),
        )

    provider = RetellVoicePlatformProvider(
        api_key="k", from_number="+15551110000", http_client=_client(handler)
    )
    request = _sample_request()
    session = await provider.start_call(request, "+15550000001")
    await session.classify()

    outcome = await session.converse("disclosure", request.ask, request.context)

    assert outcome.cost_breakdown_usd == {"twilio_telephony": pytest.approx(0.30)}


async def test_cost_usd_and_breakdown_none_when_call_cost_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/create-phone-call":
            return _create_call_response()
        return httpx.Response(200, json=_ended_call_record())

    provider = RetellVoicePlatformProvider(
        api_key="k", from_number="+15551110000", http_client=_client(handler)
    )
    request = _sample_request()
    session = await provider.start_call(request, "+15550000001")
    await session.classify()

    outcome = await session.converse("disclosure", request.ask, request.context)

    assert outcome.cost_usd is None
    assert outcome.cost_breakdown_usd is None


# ---------------------------------------------------------------------------
# Unreachable Protocol methods — Retell's agent owns IVR/hold internally
# ---------------------------------------------------------------------------


async def test_navigate_menu_wait_on_hold_and_request_callback_raise() -> None:
    session = RetellVoiceCallSession(
        client=_client(lambda r: httpx.Response(500)),
        call_id="call_123",
        poll_interval_seconds=1,
        poll_timeout_seconds=1,
        analysis_poll_timeout_seconds=1,
    )

    with pytest.raises(RuntimeError, match="unreachable for Retell"):
        await session.navigate_menu()
    with pytest.raises(RuntimeError, match="unreachable for Retell"):
        await session.wait_on_hold()
    with pytest.raises(RuntimeError, match="unreachable for Retell"):
        await session.request_callback()
