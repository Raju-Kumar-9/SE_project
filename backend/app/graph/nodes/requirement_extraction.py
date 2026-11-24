"""
Requirement Extraction agent — turns filled slots into schema-conformant
requirement rows.

PHASE 0: one placeholder requirement per filled slot, restating the raw slot
value, with confidence_score fixed at 0.3. Retained below as `_stub_extraction`,
used when STUB_MODE=true and as the safety fallback if the LLM call fails or
returns something unparseable.

PHASE 1 (current): real LLM call that can extract *multiple* distinct
requirements out of a single slot's value (a slot's raw answer often implies
several requirements at once — e.g. "documents_and_data_collected" might
imply both a data-capture requirement and a data-retention requirement),
with a real confidence score per requirement and a properly written
requirement statement instead of the raw slot value restated verbatim.
"""
from app.config import settings
from app.graph.state import PipelineState, REQUIRED_SLOTS
from app.llm.client import call_llm_json

_ID_PREFIX = {
    "business_goal_and_target_customers": "BR",
    "user_roles": "BR",
    "application_flow": "FR",
    "eligibility_rules": "FR",
    "documents_and_data_collected": "FR",
    "credit_bureau_integration": "FR",
    "approval_process_and_thresholds": "FR",
    "rejection_reappeal_process": "FR",
    "disbursement_method": "FR",
    "repayment_emi_terms": "FR",
    "authentication_and_esign": "SR",
    "notifications": "FR",
    "regulatory_jurisdiction": "CR",
    "existing_system_integrations": "FR",
    "timeline_and_budget": "BR",
    "expected_frequency_of_change": "BR",
    "regulatory_audit_criticality": "CR",
}

_VALID_CATEGORIES = {
    "business", "stakeholder", "functional", "security", "privacy", "regulatory",
    "performance", "availability", "usability", "data-management", "integration",
    "audit-reporting", "operational",
}
_VALID_PRIORITIES = {"low", "medium", "high", "critical"}


def _requirement_id(prefix: str, counter: int, state: PipelineState) -> str:
    """Keep human-readable IDs unique across sessions in the shared database."""
    session_id = str(state.get("session_id") or "session").replace("-", "")[:8].upper()
    return f"{prefix}-LOAN-{counter:03d}-{session_id}"


_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "requirements": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "slot": {"type": "STRING", "enum": [*REQUIRED_SLOTS, "unmapped"]},
                    "statement": {"type": "STRING"},
                    "category": {
                        "type": "ARRAY",
                        "items": {"type": "STRING", "enum": sorted(_VALID_CATEGORIES)},
                    },
                    "priority": {"type": "STRING", "enum": sorted(_VALID_PRIORITIES)},
                    "acceptance_criteria": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "confidence_score": {"type": "NUMBER", "minimum": 0, "maximum": 1},
                },
                "required": ["slot", "statement", "category", "priority", "acceptance_criteria", "confidence_score"],
            },
        },
        "sdlc_factor_inputs": {
            "type": "OBJECT",
            "properties": {
                "expected_frequency_of_change": {"type": "STRING"},
                "regulatory_audit_criticality": {"type": "STRING"},
                "existing_system_integrations": {"type": "STRING"},
                "timeline_and_budget": {"type": "STRING"},
            },
        },
    },
    "required": ["requirements"],
}

_SYSTEM_PROMPT = (
    "You are the Requirement Extraction agent in a requirement-gathering system for "
    "a personal/consumer loan origination application in the financial sector. You "
    "will be given a set of filled information slots from a stakeholder interview. "
    "For each slot, extract one or more distinct, schema-conformant requirements "
    "genuinely implied by that slot's value — do not invent facts the slot value "
    "doesn't support, and only extract more than one requirement per slot when the "
    "value actually implies more than one distinct thing the system shall do.\n\n"
    "Valid categories (multi-label allowed): " + ", ".join(sorted(_VALID_CATEGORIES)) + ".\n"
    "Valid priorities: " + ", ".join(sorted(_VALID_PRIORITIES)) + ".\n\n"
    "Respond with ONLY a JSON object, no other text, in exactly this shape:\n"
    "{\n"
    '  "requirements": [\n'
    "    {\n"
    '      "slot": "<source slot name, exactly as given>",\n'
    '      "statement": "<clear requirement statement, e.g. \'The system shall ...\'>",\n'
    '      "category": ["<one or more of the valid categories>"],\n'
    '      "priority": "<one of the valid priorities>",\n'
    '      "acceptance_criteria": ["<criterion>", "..."],\n'
    '      "confidence_score": <float 0.0-1.0 — your genuine confidence this '
    "requirement is correctly and completely captured from the given slot value, "
    "not a fixed number>\n"
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Write atomic, independently verifiable requirements: one system behavior or "
    "constraint per row. Split compound descriptions into separate requirements instead "
    "of making one requirement summarize the whole brief. Cover each distinct feature, "
    "user action, business rule, and quality constraint that the source actually states. "
    "Keep the response compact to avoid truncation: requirement statements should be at "
    "most 25 words, and provide at most one short acceptance criterion per requirement. "
    "Do not repeat the source brief in the output or add details the stakeholder did not provide."
    " For one-shot input, also return sdlc_factor_inputs containing only explicitly stated "
    "change-frequency, audit-criticality, integration/legacy, and timeline/budget facts; use "
    "an empty string when the brief provides no fact."
)


def _build_user_prompt(state: PipelineState) -> str:
    slot_state = state["slot_state"]
    filled = {slot: entry["value"] for slot, entry in slot_state.items() if entry["status"] == "filled"}
    if state.get("input_mode") == "one_shot":
        return (
            "Input mode: one-shot stakeholder brief. Extract requirements directly from this "
            "description. Do not invent unspecified behavior; use the slot value 'unmapped' when no single "
            "slot accurately represents the source. Return concise atomic requirements only.\n\n"
            f"Stakeholder brief:\n{state.get('initial_description') or state.get('user_message', '')}"
        )
    return f"Filled slots (JSON):\n{filled}"


def requirement_extraction_node(state: PipelineState) -> PipelineState:
    if settings.STUB_MODE:
        return _stub_extraction(state)

    try:
        system_prompt = _SYSTEM_PROMPT
        if state.get("input_mode") == "one_shot":
            system_prompt += (
                "\n\nFor one-shot input, extract requirements from the full stakeholder brief, "
                "not only the slot summary. Do not invent unstated details. Use 'unmapped' for "
                "slot when the source is the overall brief rather than one specific slot."
            )
        result = call_llm_json(
            system_prompt,
            _build_user_prompt(state),
            max_tokens=8192,
            response_schema=_RESPONSE_SCHEMA,
        )
        raw_requirements = result.get("requirements", []) or []

        if state.get("input_mode") == "one_shot":
            factor_inputs = result.get("sdlc_factor_inputs", {}) or {}
            brief = state.get("initial_description") or state.get("user_message", "")
            for slot in (
                "expected_frequency_of_change",
                "regulatory_audit_criticality",
                "existing_system_integrations",
                "timeline_and_budget",
            ):
                value = factor_inputs.get(slot)
                if isinstance(value, str) and value.strip():
                    state["slot_state"][slot].update(
                        {"status": "filled", "value": value.strip()}
                    )
                    state["slot_state"][slot]["raw_turns"].append(brief)

        extracted: list[dict] = []
        counters: dict[str, int] = {}
        for raw in raw_requirements:
            if not isinstance(raw, dict) or not raw.get("statement"):
                continue
            slot = raw.get("slot") if raw.get("slot") in REQUIRED_SLOTS else None
            if slot is None and state.get("input_mode") == "one_shot":
                # Preserve provenance when a brief-level requirement does not
                # fit one of the interview's narrower slots.
                slot = "one_shot_description"
            prefix = _ID_PREFIX.get(slot, "FR")
            counters[prefix] = counters.get(prefix, 0) + 1
            req_id = _requirement_id(prefix, counters[prefix], state)

            category = [c for c in (raw.get("category") or []) if c in _VALID_CATEGORIES] or ["functional"]
            priority = raw.get("priority") if raw.get("priority") in _VALID_PRIORITIES else None
            try:
                confidence = float(raw.get("confidence_score", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))

            extracted.append(
                {
                    "id": req_id,
                    "statement": str(raw["statement"]).strip(),
                    "category": category,
                    "source_stakeholder": "customer",
                    "business_justification": None,
                    "priority": priority,
                    "dependencies": [],
                    "assumptions": [],
                    "acceptance_criteria": list(raw.get("acceptance_criteria") or []),
                    "applicable_regulations": [],
                    "risk_level": None,
                    "confidence_score": confidence,
                    "approval_status": "pending",
                    "source_slot": slot,
                }
            )

        if not extracted:
            raise ValueError("LLM returned zero usable requirements")

        state["extracted_requirements"] = extracted
        state.setdefault("audit_events", []).append(
            {"agent": "requirement_extraction", "event": "llm_extraction", "count": len(extracted)}
        )
    except Exception as exc:
        state.setdefault("audit_events", []).append(
            {"agent": "requirement_extraction", "event": "llm_error_fallback_to_stub", "error": str(exc)}
        )
        state = _stub_extraction(state)

    return state


def _stub_extraction(state: PipelineState) -> PipelineState:
    """Deterministic Phase 0 behavior — used when STUB_MODE=true, or as the
    fallback if the Phase 1 LLM call fails or returns nothing usable."""
    slot_state = state["slot_state"]
    extracted: list[dict] = []
    if state.get("input_mode") == "one_shot":
        brief = state.get("initial_description") or state.get("user_message", "")
        if brief.strip():
            extracted.append(
                {
                    "id": _requirement_id("FR", 1, state),
                    "statement": f"[STUB] Initial requirement summary from stakeholder brief: {brief.strip()}",
                    "category": ["functional"],
                    "source_stakeholder": "customer",
                    "business_justification": None,
                    "priority": None,
                    "dependencies": [],
                    "assumptions": [],
                    "acceptance_criteria": [],
                    "applicable_regulations": [],
                    "risk_level": None,
                    "confidence_score": 0.3,
                    "approval_status": "pending",
                    "source_slot": "one_shot_description",
                }
            )
        state["extracted_requirements"] = extracted
        state.setdefault("audit_events", []).append(
            {"agent": "requirement_extraction", "event": "one_shot_stub_extraction", "count": len(extracted)}
        )
        return state

    counter = 1
    for slot in REQUIRED_SLOTS:
        entry = slot_state[slot]
        if entry["status"] != "filled":
            continue
        prefix = _ID_PREFIX.get(slot, "FR")
        req_id = _requirement_id(prefix, counter, state)
        counter += 1
        extracted.append(
            {
                "id": req_id,
                "statement": f"[STUB] Derived from slot '{slot}': {entry['value']}",
                "category": ["business" if prefix == "BR" else "functional"],
                "source_stakeholder": "customer",
                "business_justification": None,
                "priority": None,
                "dependencies": [],
                "assumptions": [],
                "acceptance_criteria": [],
                "applicable_regulations": [],
                "risk_level": None,
                "confidence_score": 0.3,
                "approval_status": "pending",
                "source_slot": slot,
            }
        )

    state["extracted_requirements"] = extracted
    state.setdefault("audit_events", []).append(
        {"agent": "requirement_extraction", "event": "stub_extraction", "count": len(extracted)}
    )
    return state
