"""Phase 3 SDLC scoring and score-constrained optional narration."""
from app.config import settings
from app.graph.sdlc_scoring import score_project
from app.graph.state import PipelineState
from app.llm.client import call_llm_json, call_sdlc_agent


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


def _validate_agent_analysis(result: dict, methods: list[str]) -> dict:
    if not isinstance(result, dict) or not isinstance(result.get("summary"), str) or not result["summary"].strip():
        raise ValueError("SDLC agent response must contain a non-empty summary string")
    per_method = result.get("per_method")
    if not isinstance(per_method, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("method"), str)
        or not isinstance(item.get("explanation"), str)
        or not item["method"].strip()
        or not item["explanation"].strip()
        for item in per_method
    ):
        raise ValueError("SDLC agent response per_method must contain method and explanation strings")
    if [item["method"] for item in per_method] != methods:
        raise ValueError("SDLC agent response methods do not match the computed ranking")
    risks = result.get("risks")
    if not isinstance(risks, list) or any(not isinstance(risk, str) for risk in risks):
        raise ValueError("SDLC agent response risks must be a list of strings")
    return {"summary": result["summary"], "per_method": per_method, "risks": risks}


def sdlc_selection_node(state: PipelineState) -> PipelineState:
    if not settings.PHASE3_ENABLED:
        raise RuntimeError("Set PHASE3_ENABLED=true to run the Phase 3 SDLC engine")
    scoring_state = state
    if state.get("finalizing_approval"):
        scoring_state = {**state, "classified_requirements": state.get("final_approved_requirements", [])}
    result, factors = score_project(scoring_state)
    ranked = result["ranked_scores"]
    methods = [row["model"] for row in ranked]
    agent_analysis = None
    if settings.SDLC_AGENT_ENABLED and not settings.STUB_MODE:
        requirements = scoring_state.get("classified_requirements") or scoring_state.get("extracted_requirements", [])
        agent_ranking = [
            {"method": row["model"], "percentage": float(row["score_percent"])}
            for row in ranked
        ]
        try:
            raw_analysis = call_sdlc_agent(
                requirements=requirements,
                ranking=agent_ranking,
                project_summary=str(scoring_state.get("initial_description") or ""),
            )
            agent_analysis = _validate_agent_analysis(raw_analysis, methods)
            state.setdefault("audit_events", []).append({
                "agent": "sdlc_selection",
                "event": "sdlc_agent_analysis",
                "methods_explained": len(methods),
            })
        except Exception as exc:
            state.setdefault("audit_events", []).append({
                "agent": "sdlc_selection",
                "event": "sdlc_agent_error",
                "error": str(exc)[:500],
            })
    state["sdlc_agent_analysis"] = agent_analysis
    if agent_analysis is not None:
        result["agent_analysis"] = agent_analysis
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
