"""Detect contradictory or duplicate requirements."""
from app.config import settings
from app.graph.state import PipelineState
from app.llm.client import call_llm_json


def conflict_detection_node(state: PipelineState) -> PipelineState:
    reqs = state.get("classified_requirements", [])
    if not settings.PHASE2_ENABLED or settings.STUB_MODE:
        state["conflicts"] = []
        state.setdefault("audit_events", []).append({"agent": "conflict_detection", "event": "stub_noop", "conflicts": 0})
        return state
    if len(reqs) < 2:
        state["conflicts"] = []
        return state

    prompt = (
        "Review these requirements for direct contradictions or duplicates. Only report clear cases; "
        "do not infer conflict merely because details are absent. Return JSON only: "
        '{"conflicts":[{"requirement_ids":["id1","id2"],"kind":"contradiction|duplicate",'
        '"explanation":"...","confidence":0.0}]}\nRequirements: '
        + str([{"id": r["id"], "statement": r["statement"]} for r in reqs])
    )
    result = call_llm_json("You are a conservative requirements conflict analyst.", prompt)
    known = {r["id"] for r in reqs}
    conflicts = []
    for item in result.get("conflicts", []):
        ids = item.get("requirement_ids", []) if isinstance(item, dict) else []
        if len(ids) >= 2 and all(i in known for i in ids) and item.get("kind") in {"contradiction", "duplicate"}:
            try:
                confidence = min(1.0, max(0.0, float(item.get("confidence", 0))))
            except (ValueError, TypeError):
                confidence = 0.0
            if confidence >= 0.55:
                conflicts.append({"requirement_ids": ids, "kind": item["kind"], "explanation": str(item.get("explanation", "")), "confidence": confidence})
    state["conflicts"] = conflicts
    state.setdefault("audit_events", []).append({"agent": "conflict_detection", "event": "llm_conflict_detection", "count": len(conflicts)})
    return state
