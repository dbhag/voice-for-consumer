"""Real voice-platform adapter for Retell AI. Implements
`engine.providers.base.VoicePlatformProvider` / `VoiceCallSession` — see
`engine/providers/mock.py` for the reference shape of the Protocol this
fills in, and `engine/providers/base.py`'s docstrings for the structural
note this file is the concrete case of.

Verified against Retell's current API docs (docs.retellai.com), not
memory: POST /v2/create-phone-call and GET /v2/get-call/{call_id}.

STRUCTURAL MISMATCH, stated plainly rather than papered over: Retell's
call API is one atomic operation. `retell_llm_dynamic_variables` — where
ask/return_fields/context_summary have to go — is set at call *creation*,
because Retell's own agent is templated with those variables (Retell's
own double-brace `{{var}}` syntax — see prompts/dialogue/v1/system.txt)
and starts speaking them the moment the call connects. There is no
mid-call "send more context now" endpoint. Practically, that means:

- `classify()` blocks (polling `get-call`) until Retell reports the call
  has actually ended, then classifies *retroactively* from the finished
  call's `disconnection_reason` / `call_analysis.in_voicemail`.
- By the time `classify()` returns HUMAN, the entire conversation already
  happened inside Retell's agent. So `navigate_menu()`, `wait_on_hold()`,
  and `request_callback()` are unreachable for this adapter — classify()
  never returns IVR or HOLD — and are implemented as loud failures
  (RuntimeError) rather than silently doing something wrong if ever hit.
- `converse()`'s `disclosure`/`primary_question`/`context` arguments are
  moot by the time it's called (the call already happened using whatever
  was baked into `retell_llm_dynamic_variables` at start_call time) —
  it just translates the transcript Retell already produced.
- `hangup()` is a no-op: there's nothing left to hang up.

Cost-guardrail consequence worth flagging: `engine.call_loop`'s
`hold_abandon_seconds` wraps `wait_on_hold()`, which this adapter never
reaches — it provides no protection against a stuck Retell call. This
adapter's own `poll_timeout_seconds` is the equivalent safety net; the two
are not the same knob, and misconfiguring one does not help the other.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from engine.models import (
    ClassifyAnswer,
    ConverseOutcome,
    HoldOutcome,
    MenuOutcome,
    Request,
    TranscriptTurn,
)

DEFAULT_BASE_URL = "https://api.retellai.com"

# disconnection_reason values, per https://docs.retellai.com/api-references/get-call.
# Retell distinguishes far more failure modes than engine.models.ReachFailure has
# room for (dial_failed, invalid_destination, sip_routing_error,
# telephony_provider_permission_denied, telephony_provider_unavailable,
# registered_call_timeout, no_valid_payment, scam_detected, marked_as_spam,
# concurrency_limit_reached, no_concurrency_fallback all mean "never connected"
# but aren't specifically busy/voicemail/no-answer). Widening ReachFailure to
# carry that distinction would be an engine/ change, out of scope here — every
# reason below that isn't voicemail/busy collapses onto
# ClassifyAnswer.VM_NO_ANSWER_BUSY -> call_loop's existing ReachFailure.NO_ANSWER
# bucket. Real information loss, flagged rather than hidden.
_VOICEMAIL_REASONS = {"voicemail_reached"}
_BUSY_REASONS = {"dial_busy"}
_OTHER_NO_CONNECT_REASONS = {
    "dial_no_answer",
    "dial_failed",
    "invalid_destination",
    "telephony_provider_permission_denied",
    "telephony_provider_unavailable",
    "sip_routing_error",
    "registered_call_timeout",
    "no_valid_payment",
    "scam_detected",
    "marked_as_spam",
    "concurrency_limit_reached",
    "no_concurrency_fallback",
}
_ENDED_CALL_STATUSES = {"ended", "error"}

# Retell's transcript_object role values -> our TranscriptTurn.speaker Literal
# (engine/models.py, not touched here). "transfer_target" (a human the call was
# transferred to) has no matching option in that Literal — mapped to "human" as
# the closer of the two available choices (it's a person, not a menu), which
# loses the "original callee vs. transfer target" distinction. Flagged, not
# guessed silently.
_ROLE_MAP: dict[str, Literal["agent", "human", "ivr"]] = {
    "agent": "agent",
    "user": "human",
    "transfer_target": "human",
}


def _humanize_field(field_name: str) -> str:
    return field_name.replace("_", " ")


def _spoken_label(field_name: str, hint_pack: dict[str, Any] | None) -> str:
    labels: dict[str, str] = (hint_pack or {}).get("field_labels", {})
    return labels.get(field_name, _humanize_field(field_name))


def render_context_summary(context: dict[str, Any]) -> str:
    """The single deterministic formatter the hard rule depends on: the same
    context always renders to the exact same string, in a stable (sorted-key)
    order — never JSON. The model parses this as prose it can quote from or
    decline to go beyond, not a data structure; formatting drift between
    calls would undermine that.
    """
    parts = []
    for key in sorted(context.keys()):
        label = key.replace("_", " ").capitalize()
        parts.append(f"{label}: {context[key]}.")
    return " ".join(parts)


def build_dynamic_variables(
    request: Request, hint_pack: dict[str, Any] | None
) -> dict[str, str]:
    """retell_llm_dynamic_variables must be dict[str, str] per Retell's API
    (additionalProperties: string) — return_fields is joined into one
    string, not passed as a list. Keys here must exactly match the
    {{double-brace}} names referenced in prompts/dialogue/v1/system.txt
    (ask, return_fields, context_summary) — Retell silently leaves any
    unmatched {{placeholder}} as literal text if the names ever drift.

    No "opening_purpose" here on purpose: the disclosure/consent sentence
    in the prompt is fixed, non-interpolated text — the legally-loaded
    recording-consent line must never have any variable content flow into
    it. Reason-for-calling folds into `ask` instead.
    """
    spoken_fields = ", ".join(_spoken_label(f, hint_pack) for f in request.return_fields)
    return {
        "ask": request.ask,
        "return_fields": spoken_fields,
        "context_summary": render_context_summary(request.context),
    }


def _translate_transcript(call_record: dict[str, Any]) -> list[TranscriptTurn]:
    # turn_id preserves conversation order, which is what call_loop/extraction
    # actually rely on. Retell's transcript_object doesn't give clean
    # per-utterance absolute timestamps in this shape, so TranscriptTurn.
    # timestamp falls back to its own now()-at-construction default rather
    # than a fabricated per-turn time.
    utterances = call_record.get("transcript_object") or []
    turns = []
    for i, utterance in enumerate(utterances):
        speaker = _ROLE_MAP.get(utterance.get("role"), "human")
        turns.append(TranscriptTurn(turn_id=i, speaker=speaker, text=utterance.get("content", "")))
    return turns


def _extract_cost_usd(call_record: dict[str, Any]) -> float | None:
    """Real billed cost, per https://docs.retellai.com/api-references/get-call
    — call_analysis.call_cost.combined_cost, in cents. None (not 0.0) if
    Retell hasn't attached cost data to this call record.
    """
    combined_cost_cents = call_record.get("call_analysis", {}).get("call_cost", {}).get(
        "combined_cost"
    )
    if combined_cost_cents is None:
        return None
    return float(combined_cost_cents) / 100


class RetellVoiceCallSession:
    def __init__(
        self,
        client: httpx.AsyncClient,
        call_id: str,
        poll_interval_seconds: float,
        poll_timeout_seconds: float,
        analysis_poll_timeout_seconds: float,
    ) -> None:
        self._client = client
        self._call_id = call_id
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds
        self._analysis_poll_timeout_seconds = analysis_poll_timeout_seconds
        self._call_record: dict[str, Any] | None = None

    async def _fetch_finished_call(self) -> dict[str, Any]:
        # Verified against Retell's live get-call docs (docs.retellai.com):
        # call_status hits "ended"/"error" the moment the call disconnects,
        # but call_analysis (custom_analysis_data — our refused_to_quote/
        # refusal_reason — plus call_summary, cost) is populated
        # *asynchronously* afterward ("Available after call ends. Subscribe
        # to call_analyzed webhook... once ready."). Returning the instant
        # call_status flips would read an empty call_analysis and silently
        # misreport "not refused" / cost None on every call. So: once ended,
        # keep polling for call_analysis specifically, bounded by its own
        # shorter timeout — best-effort, not another indefinite wait.
        elapsed = 0.0
        ended_record: dict[str, Any] | None = None
        ended_elapsed = 0.0
        while True:
            response = await self._client.get(f"/v2/get-call/{self._call_id}")
            response.raise_for_status()
            record: dict[str, Any] = response.json()
            if record.get("call_status") in _ENDED_CALL_STATUSES:
                if ended_record is None:
                    ended_elapsed = elapsed
                ended_record = record
                if record.get("call_analysis"):
                    return record
                if elapsed - ended_elapsed >= self._analysis_poll_timeout_seconds:
                    return record
            if elapsed >= self._poll_timeout_seconds:
                # Not a Retell-reported outcome — our own safety net so a
                # stuck call can't hang this coroutine forever. Treated as a
                # no-connect rather than raising, so the job keeps moving;
                # see the module docstring re: this not being the same
                # guardrail as engine.call_loop's hold_abandon_seconds.
                fallback = ended_record or record
                fallback["call_status"] = "ended"
                fallback["disconnection_reason"] = "registered_call_timeout"
                return fallback
            await asyncio.sleep(self._poll_interval_seconds)
            elapsed += self._poll_interval_seconds

    async def classify(self) -> ClassifyAnswer:
        self._call_record = await self._fetch_finished_call()
        reason = self._call_record.get("disconnection_reason")
        in_voicemail = self._call_record.get("call_analysis", {}).get("in_voicemail", False)
        if (
            in_voicemail
            or reason in _VOICEMAIL_REASONS
            or reason in _BUSY_REASONS
            or reason in _OTHER_NO_CONNECT_REASONS
        ):
            return ClassifyAnswer.VM_NO_ANSWER_BUSY
        return ClassifyAnswer.HUMAN

    async def navigate_menu(self) -> MenuOutcome:
        raise RuntimeError(
            "unreachable for Retell: classify() never returns IVR, because "
            "Retell's own agent already handled any menu before classify() "
            "returns — see engine/providers/retell.py's module docstring"
        )

    async def wait_on_hold(self) -> HoldOutcome:
        raise RuntimeError(
            "unreachable for Retell: classify() never returns HOLD; note "
            "engine.call_loop's hold_abandon_seconds guardrail wraps this "
            "method and so never engages for Retell calls — see "
            "engine/providers/retell.py's module docstring"
        )

    async def request_callback(self) -> None:
        raise RuntimeError(
            "unreachable for Retell: classify() never returns IVR, so the "
            "call loop never reaches a callback-offer branch for this adapter"
        )

    async def converse(
        self, disclosure: str, primary_question: str, context: dict[str, object]
    ) -> ConverseOutcome:
        # disclosure/primary_question/context arrive too late to matter: the
        # call already ran to completion inside Retell's agent, using
        # whatever build_dynamic_variables() baked in at start_call() time.
        # This just translates what already happened.
        if self._call_record is None:
            raise RuntimeError("converse() called before classify() populated the call record")
        transcript = _translate_transcript(self._call_record)
        # Retell has no built-in "declined to quote" signal — this depends
        # entirely on the Retell agent being configured (in the Retell
        # dashboard) with a custom post-call analysis field named
        # "refused_to_quote" (+ optional "refusal_reason"). If that schema
        # isn't configured on the agent, custom_analysis_data won't have the
        # key and this always reads as not-refused — a real gap, not a
        # guess: there's no way to distinguish "agent wasn't configured to
        # detect this" from "genuinely wasn't refused" from our side.
        #
        # Consent-gate false-positive (incident: mis-transcribed "yo" read as
        # a refusal, agent hung up) — the fix lives in prompts/dialogue/v1/
        # system.txt's consent-gate paragraph (ambiguous replies get one
        # re-ask; only a clear refusal ends the call; a pre-disclosure
        # greeting is never a consent answer), not here. Deliberately NOT
        # re-deriving `refused` from transcript text with a second,
        # independent keyword heuristic in this adapter — that would just
        # relocate the exact same class of bug (a naive text match
        # misreading an ambiguous/mis-transcribed word) rather than fix it.
        # This adapter trusts `refused_to_quote` as already reflecting the
        # prompt's clear-refusal-only bar; if that bar is ever violated
        # again, the fix belongs in the prompt, not a patch here.
        custom_analysis = self._call_record.get("call_analysis", {}).get(
            "custom_analysis_data", {}
        )
        refused = bool(custom_analysis.get("refused_to_quote", False))
        refusal_reason = custom_analysis.get("refusal_reason") if refused else None
        return ConverseOutcome(
            transcript=transcript,
            refused=refused,
            refusal_reason=refusal_reason,
            cost_usd=_extract_cost_usd(self._call_record),
        )

    async def hangup(self) -> None:
        # No-op: Retell's call already ended before classify() returned.
        pass


class RetellVoicePlatformProvider:
    def __init__(
        self,
        api_key: str,
        from_number: str,
        base_url: str | None = None,
        agent_id: str | None = None,
        hint_pack: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
        poll_interval_seconds: float = 3.0,
        poll_timeout_seconds: float = 600.0,
        analysis_poll_timeout_seconds: float = 30.0,
    ) -> None:
        self._from_number = from_number
        self._agent_id = agent_id
        self._hint_pack = hint_pack
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds
        self._analysis_poll_timeout_seconds = analysis_poll_timeout_seconds
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url or DEFAULT_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def start_call(self, request: Request, phone_number: str) -> RetellVoiceCallSession:
        payload: dict[str, Any] = {
            "from_number": self._from_number,
            "to_number": phone_number,
            "retell_llm_dynamic_variables": build_dynamic_variables(request, self._hint_pack),
        }
        if self._agent_id:
            payload["override_agent_id"] = self._agent_id

        response = await self._client.post("/v2/create-phone-call", json=payload)
        response.raise_for_status()
        call_id: str = response.json()["call_id"]

        return RetellVoiceCallSession(
            self._client,
            call_id,
            self._poll_interval_seconds,
            self._poll_timeout_seconds,
            self._analysis_poll_timeout_seconds,
        )
