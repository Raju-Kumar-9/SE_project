"""
Graph builder — wires all 13 agents.

Flow per invocation (one user message = one graph invocation):

    START -> coordinator --(interview incomplete)--> stakeholder_interaction
                                                        --(still incomplete)--> END
                                                        --(now complete)--> requirement_extraction
                          --(interview complete)-->  requirement_extraction
                                                        -> core passthrough -> sdlc_selection (default)
                                                        -> optional analysis chain -> sdlc_selection
                                                        -> final documentation
                                                        -> validation
                                                        -> END (normal client flow)

Internal human approval is an optional path controlled by REVIEWER_APPROVAL_REQUIRED.

Optional analysis agents are bypassed by default. When enabled, clarification
pauses with a persisted question and conflict checks rerun after the answer.
"""
from langgraph.graph import END, StateGraph

from app.config import settings

from app.graph.nodes.classification import classification_node
from app.graph.nodes.clarification import clarification_node
from app.graph.nodes.compliance import compliance_node
from app.graph.nodes.conflict_detection import conflict_detection_node
from app.graph.nodes.coordinator import coordinator_node, route_after_coordinator
from app.graph.nodes.documentation import documentation_node
from app.graph.nodes.human_approval import human_approval_node
from app.graph.nodes.requirement_extraction import requirement_extraction_node
from app.graph.nodes.risk_analysis import risk_analysis_node
from app.graph.nodes.sdlc_selection import sdlc_selection_node
from app.graph.nodes.security_privacy import security_privacy_node
from app.graph.nodes.stakeholder_interaction import stakeholder_interaction_node
from app.graph.nodes.validation import validation_node
from app.graph.state import PipelineState


def core_requirement_passthrough_node(state: PipelineState) -> PipelineState:
    """Expose extracted rows under the downstream baseline key without analysis agents."""
    state["classified_requirements"] = state.get("extracted_requirements", [])
    state["conflicts"] = []
    state["clarification_flags"] = []
    state["compliance_mappings"] = []
    state["security_privacy_findings"] = []
    state["risk_assessments"] = []
    state["escalations"] = []
    state.setdefault("audit_events", []).append({
        "agent": "coordinator",
        "event": "optional_analysis_agents_skipped",
        "requirement_count": len(state["classified_requirements"]),
    })
    return state


def route_after_extraction(state: PipelineState) -> str:
    return "classification" if settings.OPTIONAL_ANALYSIS_AGENTS_ENABLED else "core_requirement_passthrough"


def route_after_interaction(state: PipelineState) -> str:
    """Start analysis on the same turn that fills the final interview slot."""
    return "requirement_extraction" if state.get("interview_complete") else END


def route_after_clarification(state: PipelineState) -> str:
    if state.get("clarification_answer_pending"):
        return "conflict_detection"
    if state.get("pending_clarification"):
        return END
    return "compliance"


def route_after_approval(state: PipelineState) -> str:
    if state.get("regenerate_documentation"):
        return "sdlc_selection" if state.get("rescore_sdlc") else "documentation"
    return "sdlc_selection" if state.get("finalizing_approval") else END


def route_after_sdlc(state: PipelineState) -> str:
    if state.get("finalizing_approval"):
        return "final_documentation"
    if not settings.REVIEWER_APPROVAL_REQUIRED:
        return "complete_analysis"
    return "documentation"


def complete_analysis_node(state: PipelineState) -> PipelineState:
    """Finish an analysis run without requiring the client to approve outputs."""
    requirements = state.get("classified_requirements", [])
    state["finalizing_approval"] = True
    state["final_approved_requirements"] = [dict(req) for req in requirements]
    state["approval_pending"] = False
    state["analysis_complete"] = True
    state["reviewer_approval_required"] = False
    state.setdefault("audit_events", []).append({
        "agent": "coordinator",
        "event": "analysis_completed_without_client_approval",
        "requirement_count": len(requirements),
    })
    return state


def route_after_validation(state: PipelineState) -> str:
    if state.get("finalizing_approval"):
        return END
    use_reviewer = settings.PHASE4_ENABLED and settings.REVIEWER_APPROVAL_REQUIRED
    return "human_approval" if use_reviewer else "complete_analysis"


def build_graph(checkpointer=None):
    graph = StateGraph(PipelineState)

    graph.add_node("coordinator", coordinator_node)
    graph.add_node("stakeholder_interaction", stakeholder_interaction_node)
    graph.add_node("requirement_extraction", requirement_extraction_node)
    graph.add_node("core_requirement_passthrough", core_requirement_passthrough_node)
    graph.add_node("classification", classification_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("conflict_detection", conflict_detection_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node("security_privacy", security_privacy_node)
    graph.add_node("risk_analysis", risk_analysis_node)
    graph.add_node("sdlc_selection", sdlc_selection_node)
    graph.add_node("documentation", documentation_node)
    graph.add_node("final_documentation", documentation_node)
    graph.add_node("validation", validation_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("complete_analysis", complete_analysis_node)

    graph.set_entry_point("coordinator")

    graph.add_conditional_edges(
        "coordinator",
        route_after_coordinator,
        {
            "stakeholder_interaction": "stakeholder_interaction",
            "requirement_extraction": "requirement_extraction",
            "clarification": "clarification",
        },
    )

    graph.add_conditional_edges(
        "stakeholder_interaction",
        route_after_interaction,
        {"requirement_extraction": "requirement_extraction", END: END},
    )

    graph.add_conditional_edges(
        "requirement_extraction",
        route_after_extraction,
        {"classification": "classification", "core_requirement_passthrough": "core_requirement_passthrough"},
    )
    graph.add_edge("core_requirement_passthrough", "sdlc_selection")
    graph.add_edge("classification", "conflict_detection")
    graph.add_edge("conflict_detection", "clarification")
    graph.add_conditional_edges(
        "clarification",
        route_after_clarification,
        {"conflict_detection": "conflict_detection", "compliance": "compliance", END: END},
    )
    graph.add_edge("compliance", "security_privacy")
    graph.add_edge("security_privacy", "risk_analysis")
    graph.add_edge("risk_analysis", "sdlc_selection")
    graph.add_conditional_edges(
        "sdlc_selection",
        route_after_sdlc,
        {"documentation": "documentation", "final_documentation": "final_documentation",
         "complete_analysis": "complete_analysis"},
    )
    graph.add_edge("complete_analysis", "final_documentation")
    graph.add_edge("final_documentation", "validation")
    graph.add_edge("documentation", "validation")
    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {"human_approval": "human_approval", "complete_analysis": "complete_analysis", END: END},
    )
    graph.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {"sdlc_selection": "sdlc_selection", "documentation": "documentation", END: END},
    )

    return graph.compile(checkpointer=checkpointer)


compiled_graph = build_graph()
_durable_graph = compiled_graph


def configure_checkpointer(checkpointer) -> None:
    global _durable_graph
    _durable_graph = build_graph(checkpointer)


def get_compiled_graph():
    return _durable_graph
