"""Multi-label requirement classification."""
from app.config import settings
from app.graph.state import PipelineState
from app.llm.client import call_llm_json

CATEGORIES = {
    "business", "stakeholder", "functional", "security", "privacy", "regulatory",
    "performance", "availability", "usability", "data-management", "integration",
    "audit-reporting", "operational",
}


def classification_node(state: PipelineState) -> PipelineState:
    requirements = state.get("extracted_requirements", [])
    if not settings.PHASE2_ENABLED or settings.STUB_MODE:
        state["classified_requirements"] = requirements
        state.setdefault("audit_events", []).append({"agent": "classification", "event": "stub_passthrough"})
        return state
    if not requirements:
        state["classified_requirements"] = []
        return state

    prompt = (
        "Classify each software requirement for a personal/consumer loan origination app. "
        "Assign every applicable label from: " + ", ".join(sorted(CATEGORIES)) + ". "
        "Do not rewrite IDs or statements. Return JSON only: "
        '{"classifications":[{"id":"...","categories":["..."]}]}\nRequirements: '
        + str([{"id": r["id"], "statement": r["statement"]} for r in requirements])
    )
    result = call_llm_json("You are a careful multi-label requirements classifier.", prompt)
    labels = {row.get("id"): row.get("categories", []) for row in result.get("classifications", []) if isinstance(row, dict)}
    classified = []
    for req in requirements:
        valid = sorted({x for x in labels.get(req["id"], []) if x in CATEGORIES})
        classified.append({**req, "category": valid or req.get("category", ["functional"])})
    state["classified_requirements"] = classified
    state.setdefault("audit_events", []).append({"agent": "classification", "event": "multi_label_classification", "count": len(classified)})
    return state
