"""
Shared LangGraph state for the 13-agent pipeline.

The slot tracker is deterministic backend state — NOT decided by the LLM.
Each slot has a status of "missing", "vague", or "filled".
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict
from uuid import UUID

SlotStatus = Literal["missing", "vague", "filled"]

# The 17 required slots (locked-in). The last two feed the SDLC engine directly.
REQUIRED_SLOTS: list[str] = [
    "business_goal_and_target_customers",
    "user_roles",
    "application_flow",
    "eligibility_rules",
    "documents_and_data_collected",
    "credit_bureau_integration",
    "approval_process_and_thresholds",
    "rejection_reappeal_process",
    "disbursement_method",
    "repayment_emi_terms",
    "authentication_and_esign",
    "notifications",
    "regulatory_jurisdiction",
    "existing_system_integrations",
    "timeline_and_budget",
    "expected_frequency_of_change",
    "regulatory_audit_criticality",
]

# Slots that map straight into the SDLC scoring engine (Phase 3).
SDLC_FACTOR_SLOTS: list[str] = [
    "expected_frequency_of_change",
    "regulatory_audit_criticality",
]

# Human-readable prompts used by the stub interaction agent, and as the
# fallback question bank the Phase 1 LLM version can draw on / override.
SLOT_QUESTIONS: dict[str, str] = {
    "business_goal_and_target_customers": "What's the core business goal of this loan app, and who are your target customers?",
    "user_roles": "Who are the different user roles in the system (e.g. applicant, loan officer, underwriter, admin)?",
    "application_flow": "Can you walk me through the loan application flow from a customer's perspective?",
    "eligibility_rules": "What eligibility rules determine whether an applicant qualifies (income, credit score, age, etc.)?",
    "documents_and_data_collected": "What documents and personal/financial data do you need to collect from applicants?",
    "credit_bureau_integration": "Will the system integrate with a credit bureau, and if so, which one(s)?",
    "approval_process_and_thresholds": "How does the approval process work, and are there specific approval thresholds?",
    "rejection_reappeal_process": "What happens when an application is rejected — is there a reappeal process?",
    "disbursement_method": "How will approved loans be disbursed to customers?",
    "repayment_emi_terms": "What repayment/EMI terms and schedules should the system support?",
    "authentication_and_esign": "What authentication and e-signature requirements apply to applicants?",
    "notifications": "What notifications should the system send, and through which channels?",
    "regulatory_jurisdiction": "Which regulatory jurisdiction(s) will this product operate under?",
    "existing_system_integrations": "Does this need to integrate with any existing internal systems?",
    "timeline_and_budget": "What's the expected timeline and budget for this project?",
    "expected_frequency_of_change": "How frequently do you expect requirements to change once development starts?",
    "regulatory_audit_criticality": "How critical is regulatory audit compliance for this product — is it heavily audited?",
}


class SlotEntry(TypedDict):
    status: SlotStatus
    value: str | None
    raw_turns: list[str]


class PipelineState(TypedDict, total=False):
    # --- identity / conversation ---
    session_id: UUID
    user_message: str
    input_mode: Literal["interview", "one_shot"]
    initial_description: str
    finish_input: bool
    assistant_message: str
    turn_index: int

    # --- slot tracker (deterministic, not LLM-decided) ---
    slot_state: dict[str, SlotEntry]
    interview_complete: bool
    pending_clarification: dict[str, Any] | None
    clarification_rounds: int
    clarification_answer_pending: bool
    analysis_complete: bool
    approval_pending: bool
    reviewer_approval_required: bool
    review_round: int
    regenerate_documentation: bool
    finalizing_approval: bool
    final_approved_requirements: list[dict[str, Any]]
    rescore_sdlc: bool
    approval_decisions: list[dict[str, Any]]

    # --- populated once the interview completes, in pipeline order ---
    extracted_requirements: list[dict[str, Any]]
    classified_requirements: list[dict[str, Any]]
    clarification_flags: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    compliance_mappings: list[dict[str, Any]]
    security_privacy_findings: list[dict[str, Any]]
    risk_assessments: list[dict[str, Any]]
    sdlc_recommendation: dict[str, Any]
    sdlc_agent_analysis: dict[str, Any] | None
    generated_documents: list[dict[str, Any]]
    validation_notes: list[str]
    escalations: list[str]
    approval_routing: list[dict[str, Any]]

    # --- audit ---
    audit_events: list[dict[str, Any]]


def new_slot_state() -> dict[str, SlotEntry]:
    return {
        slot: {"status": "missing", "value": None, "raw_turns": []}
        for slot in REQUIRED_SLOTS
    }


def is_interview_complete(slot_state: dict[str, SlotEntry]) -> bool:
    return all(entry["status"] == "filled" for entry in slot_state.values())


def next_missing_or_vague_slot(slot_state: dict[str, SlotEntry]) -> str | None:
    """Vague slots take priority over missing ones (follow-up beats new question)."""
    for slot in REQUIRED_SLOTS:
        if slot_state[slot]["status"] == "vague":
            return slot
    for slot in REQUIRED_SLOTS:
        if slot_state[slot]["status"] == "missing":
            return slot
    return None
