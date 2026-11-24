"""
Stakeholder Interaction agent — conducts the interview.

PHASE 0: deterministic stub — fills whichever slot is currently targeted
with the raw message verbatim and reads the next question off a static
bank. Retained below as `_stub_turn`, used when STUB_MODE=true (no API key
needed for local dev / the smoke test) and as the safety fallback if the
LLM call itself fails or returns something unparseable — a bad LLM response
should never corrupt slot state or crash the interview mid-conversation.

PHASE 1 (current): real LLM call each turn that
  1. extracts information from the user's last answer into whichever slot(s)
     it actually addresses — a single answer can fill or advance more than
     one slot at once, unlike the Phase 0 stub which only ever targets one,
  2. flags a filled slot "vague" instead of "filled" when the answer is
     incomplete, non-specific, or self-contradictory,
  3. generates the single best next question — a follow-up on a slot it just
     flagged vague, or the next missing required slot — instead of reading a
     fixed question off SLOT_QUESTIONS.
"""
from app.config import settings
from app.graph.state import (
    PipelineState,
    REQUIRED_SLOTS,
    SLOT_QUESTIONS,
    is_interview_complete,
    next_missing_or_vague_slot,
)
from app.llm.client import call_llm_json

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "slot_updates": {
            "type": "OBJECT",
            "properties": {
                slot: {
                    "type": "OBJECT",
                    "properties": {
                        "status": {"type": "STRING", "enum": ["filled", "vague"]},
                        "value": {"type": "STRING"},
                    },
                    "required": ["status", "value"],
                }
                for slot in REQUIRED_SLOTS
            },
        },
        "next_question": {"type": "STRING"},
    },
    "required": ["slot_updates", "next_question"],
}

_SYSTEM_PROMPT = (
    "You are the Stakeholder Interaction agent in a requirement-gathering system "
    "for a personal/consumer loan origination application in the financial sector. "
    "You are interviewing a stakeholder to fill in a fixed set of information slots. "
    "You do NOT decide when the interview is complete — that is tracked separately "
    "by backend state. Your job on this turn:\n\n"
    "1. Read the stakeholder's latest message.\n"
    "2. Decide which slot(s) it actually addresses — it may bear on more than one "
    "slot, or none.\n"
    "3. For each slot it addresses, decide whether the answer is specific and "
    "complete enough to mark \"filled\", or too vague/incomplete/self-contradictory "
    "to mark \"vague\" (needs a follow-up before it can count as filled).\n"
    "4. Pick the SINGLE best next question to ask: prefer a follow-up on a slot you "
    "just marked vague; otherwise ask about the highest-priority remaining missing "
    "slot.\n\n"
    "Respond with ONLY a JSON object, no other text, in exactly this shape:\n"
    "{\n"
    '  "slot_updates": {\n'
    '    "<slot_name>": {"status": "filled" | "vague", "value": "<concise restatement '
    'of what was said, or of what is still missing if vague>"}\n'
    "  },\n"
    '  "next_question": "<the single next question to ask, or empty string only if '
    'every slot is now filled>"\n'
    "}\n\n"
    "Only include a slot in slot_updates if this turn's answer actually changes it. "
    "Valid slot names are exactly: " + ", ".join(REQUIRED_SLOTS)
)


def _build_user_prompt(state: PipelineState) -> str:
    slot_state = state["slot_state"]
    slot_summary = {
        slot: {"status": entry["status"], "value": entry["value"]} for slot, entry in slot_state.items()
    }
    return (
        f"Current slot state (JSON):\n{slot_summary}\n\n"
        f"Stakeholder's latest message:\n{state.get('user_message', '')}"
    )


def stakeholder_interaction_node(state: PipelineState) -> PipelineState:
    # A free-form brief is intentionally collected verbatim and extracted only
    # after the user clicks End description. Calling the interview LLM for each
    # Add details turn is wasteful and can truncate its large slot-update JSON.
    if state.get("input_mode") == "one_shot" and not settings.STUB_MODE:
        state["interview_complete"] = False
        state["assistant_message"] = "Got it. Add more details if you like, then click End description to generate the requirements."
        state.setdefault("audit_events", []).append(
            {"agent": "stakeholder_interaction", "event": "one_shot_brief_buffered_no_llm_call"}
        )
        return state

    if settings.STUB_MODE:
        if state.get("input_mode") == "one_shot":
            state["interview_complete"] = False
            state["assistant_message"] = "Got it. Add more details if you like, then click End description to generate the requirements."
            state.setdefault("audit_events", []).append(
                {"agent": "stakeholder_interaction", "event": "one_shot_brief_stub_mode"}
            )
        else:
            state = _stub_turn(state)
            state["interview_complete"] = is_interview_complete(state["slot_state"])
        return state

    slot_state = state["slot_state"]
    user_message = state.get("user_message", "")

    try:
        system_prompt = _SYSTEM_PROMPT
        if state.get("input_mode") == "one_shot":
            system_prompt += (
                "\n\nFREE-FORM MODE: this is one of several possible brief messages. Use the "
                "current slot state as context, add or revise only facts supported by the latest "
                "message, and do not ask questions. The stakeholder will explicitly end input "
                "when ready for requirement generation."
            )
        result = call_llm_json(
            system_prompt,
            _build_user_prompt(state),
            response_schema=_RESPONSE_SCHEMA,
        )
        slot_updates = result.get("slot_updates", {}) or {}

        applied = {}
        for slot, update in slot_updates.items():
            if slot not in slot_state or not isinstance(update, dict):
                continue
            status = update.get("status")
            if status not in ("filled", "vague"):
                continue
            slot_state[slot]["status"] = status
            slot_state[slot]["value"] = update.get("value", slot_state[slot]["value"])
            slot_state[slot]["raw_turns"].append(user_message)
            applied[slot] = status

        next_question = (result.get("next_question") or "").strip()
        if not next_question:
            remaining = next_missing_or_vague_slot(slot_state)
            next_question = SLOT_QUESTIONS[remaining] if remaining else ""

        state["assistant_message"] = next_question or (
            "Thanks — that covers everything I need for now. Running the analysis pipeline..."
        )
        state.setdefault("audit_events", []).append(
            {"agent": "stakeholder_interaction", "event": "llm_turn", "slot_updates": applied}
        )
    except Exception as exc:
        # Never let an LLM failure or a malformed response corrupt slot state or
        # stall the interview — fall back to the deterministic Phase 0 behavior
        # for this one turn, and record why in the audit trail.
        state.setdefault("audit_events", []).append(
            {
                "agent": "stakeholder_interaction",
                "event": "llm_error_no_slot_mutation" if state.get("input_mode") == "one_shot" else "llm_error_fallback_to_stub",
                "error": str(exc),
            }
        )
        if state.get("input_mode") != "one_shot":
            state = _stub_turn(state)

    # Coordinator runs before the interview node, so refresh completion after
    # applying this turn's slot updates. The graph uses this to start analysis
    # immediately when the final required slot is filled.
    state["interview_complete"] = (
        False if state.get("input_mode") == "one_shot" else is_interview_complete(slot_state)
    )
    if state.get("input_mode") == "one_shot":
        state["assistant_message"] = "Got it. Add more details if you like, then click End description to generate the requirements."
    return state


def _stub_turn(state: PipelineState) -> PipelineState:
    """Deterministic Phase 0 behavior — used when STUB_MODE=true, or as the
    fallback for this turn if the Phase 1 LLM call fails."""
    slot_state = state["slot_state"]
    user_message = state.get("user_message", "").strip()
    target_slot = next_missing_or_vague_slot(slot_state)

    if target_slot is not None and user_message:
        slot_state[target_slot]["status"] = "filled"
        slot_state[target_slot]["value"] = user_message
        slot_state[target_slot]["raw_turns"].append(user_message)

    next_slot = next_missing_or_vague_slot(slot_state)
    if next_slot is None:
        state["assistant_message"] = (
            "Thanks — that covers everything I need for now. Running the analysis pipeline..."
        )
    else:
        state["assistant_message"] = SLOT_QUESTIONS[next_slot]

    state.setdefault("audit_events", []).append(
        {"agent": "stakeholder_interaction", "event": "stub_turn", "filled_slot": target_slot}
    )
    return state
