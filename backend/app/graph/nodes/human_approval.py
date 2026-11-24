"""Pause the graph for human decisions on the requirements baseline."""
from app.config import settings
from app.graph.state import PipelineState
from langgraph.types import interrupt


def human_approval_node(state: PipelineState) -> PipelineState:
    if not settings.PHASE4_ENABLED:
        state["approval_routing"] = [
            {"requirement_id": req["id"], "routed_to": "reviewer_queue", "priority": "standard", "reason": "Phase 4 disabled; placeholder only"}
            for req in state.get("classified_requirements", [])
        ]
        state["analysis_complete"] = True
        state.setdefault("audit_events", []).append({"agent": "human_approval", "event": "phase4_disabled"})
        return state

    # A modification on the last configured review pass still regenerates the
    # files, then ends without an unbounded reviewer loop.
    if state.get("analysis_complete") and state.get("regenerate_documentation"):
        state["regenerate_documentation"] = False
        state["rescore_sdlc"] = False
        state["approval_pending"] = False
        state.setdefault("audit_events", []).append({"agent": "human_approval", "event": "review_complete_after_final_document_regeneration"})
        return state

    # Must be the first operation in this node: LangGraph replays the node
    # from its start when it resumes this interrupt.
    decisions = interrupt({
        "kind": "requirements_baseline_review",
        "requirements": state.get("classified_requirements", []),
        "approval_routing": state.get("approval_routing", []),
        "generated_documents": state.get("generated_documents", []),
    })
    if not isinstance(decisions, list):
        raise ValueError("Approval resume payload must be a list of requirement decisions")
    by_id = {item.get("requirement_id"): item for item in decisions if isinstance(item, dict)}
    allowed = {row.get("requirement_id") for row in state.get("approval_routing", [])}
    applied = []
    requires_regeneration = False
    requires_rescoring = False
    for req in state.get("classified_requirements", []):
        decision = by_id.get(req.get("id"))
        if req.get("id") not in allowed or not decision:
            continue
        choice = decision.get("decision")
        if choice not in {"approved", "rejected", "modified", "regenerate_requested"}:
            raise ValueError(f"Invalid approval decision for {req['id']}")
        if choice == "modified":
            modified_statement = str(decision.get("modified_statement", "")).strip()
            if not modified_statement:
                raise ValueError(f"Modified decision for {req['id']} requires a statement")
            req["statement"] = modified_statement
            modified_criteria = decision.get("modified_acceptance_criteria")
            if modified_criteria is not None:
                req["acceptance_criteria"] = [
                    str(item).strip() for item in modified_criteria if str(item).strip()
                ]
            # The edited requirement needs a fresh decision. Keep all other
            # requirements' decisions intact for the next review round.
            req["approval_status"] = "pending"
            requires_regeneration = True
            requires_rescoring = True
        else:
            req["approval_status"] = "pending" if choice == "regenerate_requested" else choice
            requires_regeneration = requires_regeneration or choice == "regenerate_requested"
        applied.append({
            "requirement_id": req["id"],
            "decision": choice,
            "reviewer": decision.get("reviewer"),
            "notes": decision.get("notes"),
        })
    state["approval_decisions"] = applied
    state["review_round"] = int(state.get("review_round", 1))
    max_rounds = settings.PHASE4_MAX_REVIEW_ROUNDS
    if requires_regeneration:
        state["finalizing_approval"] = False
        state["final_approved_requirements"] = []
        state["regenerate_documentation"] = True
        state["rescore_sdlc"] = requires_rescoring
        if state["review_round"] < max_rounds:
            state["review_round"] += 1
            state["approval_pending"] = True
            state["analysis_complete"] = False
        else:
            state["approval_pending"] = False
            state["analysis_complete"] = True
    else:
        state["regenerate_documentation"] = False
        state["rescore_sdlc"] = False
        state["approval_pending"] = False
        state["analysis_complete"] = True
        state["finalizing_approval"] = True
        state["final_approved_requirements"] = [
            dict(req) for req in state.get("classified_requirements", [])
            if req.get("approval_status") == "approved"
        ]
    state.setdefault("audit_events", []).append({"agent": "human_approval", "event": "review_complete", "decisions": applied})
    return state
