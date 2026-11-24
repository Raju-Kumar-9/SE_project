"""Phase 3 SDLC scoring and score-constrained optional narration."""
from app.config import settings
from app.graph.sdlc_scoring import score_project
from app.graph.state import PipelineState
from app.llm.client import call_llm_json


def _deterministic_narration(ranked: list[dict], factors: dict) -> str:
    if not ranked:
        return "No SDLC recommendation could be computed because the project has no requirement inputs."
    top = ranked[0]["model"]
    next_model = ranked[1]["model"] if len(ranked) > 1 else None
    strongest = sorted(factors.items(), key=lambda item: (not item[1]["input_available"], -item[1]["rating"]))[:3]
    context = "; ".join(f"{name.replace('_', ' ')}: {info['rating']}/5" for name, info in strongest)
    if next_model:
        return f"{top} ranks first under the configured weighted factor matrix, followed by {next_model}. The ranking uses these project inputs: {context}. Treat this as decision support for project stakeholders."
    return f"{top} ranks first under the configured weighted factor matrix. The ranking uses these project inputs: {context}. Treat this as decision support for project stakeholders."


def _llm_narration(ranked: list[dict], factors: dict) -> str:
    result = call_llm_json(
        "You explain a deterministic SDLC ranking. You may not change or recalculate scores. Do not invent numeric percentages, project facts, or factors. Return JSON only: {\"narration\":\"...\"}.",
        f"Computed ranking (authoritative): {ranked}\nComputed factor ratings and evidence (authoritative): {factors}\nExplain why the leading models fit these inputs. Do not include numbers or percentages.",
        max_tokens=500,
    )
    narration = result.get("narration")
    if not isinstance(narration, str) or not narration.strip() or any(char.isdigit() for char in narration) or "%" in narration:
        raise ValueError("Narration must be text and must not introduce numeric scores")
    return narration.strip()


def sdlc_selection_node(state: PipelineState) -> PipelineState:
    if not settings.PHASE3_ENABLED:
        raise RuntimeError("Set PHASE3_ENABLED=true to run the Phase 3 SDLC engine")
    scoring_state = state
    if state.get("finalizing_approval"):
        scoring_state = {**state, "classified_requirements": state.get("final_approved_requirements", [])}
    result, factors = score_project(scoring_state)
    ranked = result["ranked_scores"]
    narration = _deterministic_narration(ranked, factors)
    narration_source = "deterministic_template"
    if settings.PHASE3_NARRATION_ENABLED and not settings.STUB_MODE:
        try:
            narration = _llm_narration(ranked, factors)
            narration_source = "llm_constrained_to_computed_scores"
        except Exception as exc:
            state.setdefault("audit_events", []).append({"agent": "sdlc_selection", "event": "narration_error_fallback", "error": str(exc)[:300]})

    coverage = sum(1 for value in factors.values() if value["input_available"])
    result["narration"] = narration
    result["narration_source"] = narration_source
    result["factor_coverage"] = {"available": coverage, "total": len(factors), "percent": round(coverage / len(factors) * 100)}
    state["sdlc_recommendation"] = result
    state.setdefault("audit_events", []).append({"agent": "sdlc_selection", "event": "deterministic_weighted_scoring", "models_ranked": len(ranked), "top_model": ranked[0]["model"] if ranked else None, "factor_coverage": coverage})
    return state
