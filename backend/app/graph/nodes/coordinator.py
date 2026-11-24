"""
Coordinator agent — controls workflow routing and assigns tasks.

This node is "real" in Phase 0 (not a stub): its job is pure routing logic,
not domain intelligence, so there's nothing to replace in a later phase.
It decides whether the graph should keep interviewing or fall through into
the analysis pipeline.
"""
from app.graph.state import PipelineState, is_interview_complete


def coordinator_node(state: PipelineState) -> PipelineState:
    if state.get("input_mode") == "one_shot":
        # Collect as many free-form messages as the stakeholder needs. Only
        # the explicit finish action starts requirement extraction.
        state["interview_complete"] = bool(state.get("finish_input"))
        if state["interview_complete"]:
            state["assistant_message"] = "Description complete. Generating requirements for review."
        state.setdefault("audit_events", []).append(
            {
                "agent": "coordinator",
                "event": "one_shot_brief_finalized" if state["interview_complete"] else "one_shot_brief_continues",
            }
        )
        return state
    slot_state = state["slot_state"]
    state["interview_complete"] = is_interview_complete(slot_state)
    state.setdefault("audit_events", []).append(
        {"agent": "coordinator", "event": "routed", "interview_complete": state["interview_complete"]}
    )
    return state


def route_after_coordinator(state: PipelineState) -> str:
    """Conditional edge target used by graph.py."""
    if state.get("pending_clarification"):
        return "clarification"
    if state.get("input_mode") == "one_shot":
        return "requirement_extraction" if state.get("finish_input") else "stakeholder_interaction"
    return "stakeholder_interaction" if not state["interview_complete"] else "requirement_extraction"
