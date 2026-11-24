"""Validate generated artifacts and prepare a risk-prioritized reviewer queue."""
from app.config import settings
from app.graph.state import PipelineState


def validation_node(state: PipelineState) -> PipelineState:
    reqs = state.get("classified_requirements", [])
    if state.get("input_mode") == "one_shot" and state.get("initial_description"):
        for req in reqs:
            if not req.get("source_slot"):
                req["source_slot"] = "one_shot_description"
    notes = []
    if not reqs:
        notes.append("No requirements were generated.")
    for req in reqs:
        if not req.get("statement"):
            notes.append(f"{req.get('id', 'unknown')}: missing statement")
        if not req.get("source_slot"):
            notes.append(f"{req.get('id', 'unknown')}: missing source slot traceability")
        if not req.get("acceptance_criteria"):
            notes.append(f"{req.get('id', 'unknown')}: no acceptance criteria supplied")
    if settings.PHASE4_ENABLED:
        docs = {d.get("type") for d in state.get("generated_documents", [])}
        for expected in ("srs", "traceability_matrix"):
            if expected not in docs:
                notes.append(f"Generated {expected} document is missing.")
    state["validation_notes"] = notes

    escalated_ids = {m.get("requirement_id") for m in state.get("compliance_mappings", []) if m.get("escalated")}
    conflict_ids = {rid for c in state.get("conflicts", []) for rid in c.get("requirement_ids", [])}
    routing = []
    # A later review round should include only requirements that still need a
    # decision. Earlier accepted/rejected decisions remain part of the baseline.
    review_reqs = [req for req in reqs if req.get("approval_status", "pending") == "pending"]
    for req in (review_reqs if settings.REVIEWER_APPROVAL_REQUIRED else []):
        req_id = req.get("id")
        risk = req.get("risk_level") or "medium"
        high_risk = risk in {"high", "critical"}
        regulatory = "regulatory" in req.get("category", [])
        priority = "high" if high_risk or regulatory or req_id in escalated_ids or req_id in conflict_ids else "standard"
        reasons = []
        if high_risk:
            reasons.append(f"{risk} risk")
        if regulatory:
            reasons.append("regulatory requirement")
        if req_id in escalated_ids:
            reasons.append("compliance escalation")
        if req_id in conflict_ids:
            reasons.append("detected conflict")
        routing.append({"requirement_id": req_id, "routed_to": "reviewer_queue", "priority": priority,
                        "reason": ", ".join(reasons) if reasons else "baseline approval required"})
    state["approval_routing"] = routing
    state["approval_pending"] = bool(
        settings.PHASE4_ENABLED and settings.REVIEWER_APPROVAL_REQUIRED and routing
    )
    state.setdefault("review_round", 1)
    if state["approval_pending"]:
        state["assistant_message"] = "The SRS and traceability matrix are ready. Requirements are waiting for reviewer decisions."
    elif not settings.REVIEWER_APPROVAL_REQUIRED:
        state["assistant_message"] = "Analysis is complete. Extracted requirements, the SDLC ranking, and documents are ready in Results."
    state.setdefault("audit_events", []).append({"agent": "validation", "event": "validation_complete", "notes": len(notes), "review_queue": len(routing)})
    return state
