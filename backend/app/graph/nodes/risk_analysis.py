"""Transparent rule-based requirement risk scoring informed by Phase 2 findings."""
from app.config import settings
from app.graph.state import PipelineState

_LEVELS = ("low", "medium", "high", "critical")


def risk_analysis_node(state: PipelineState) -> PipelineState:
    reqs = state.get("classified_requirements", [])
    if not settings.PHASE2_ENABLED or settings.STUB_MODE:
        results = [{"requirement_id": r["id"], "risk_level": "medium", "score": 0.5, "rationale": "Phase 2 disabled; placeholder only."} for r in reqs]
        state["risk_assessments"] = results
        state.setdefault("audit_events", []).append({"agent": "risk_analysis", "event": "stub_fixed_medium", "count": len(results)})
        return state
    security_by_id = {}
    for finding in state.get("security_privacy_findings", []):
        if finding.get("requirement_id"):
            security_by_id.setdefault(finding["requirement_id"], []).append(finding)
    compliance_by_id = {m["requirement_id"]: m for m in state.get("compliance_mappings", [])}
    results = []
    for req in reqs:
        score, reasons = 0.10, []
        categories = set(req.get("category", []))
        if categories & {"security", "privacy", "regulatory", "audit-reporting"}:
            score += 0.25
            reasons.append("security, privacy, regulatory, or audit category")
        risk_level = req.get("risk_level")
        if risk_level in _LEVELS:
            score += {"low": 0.0, "medium": 0.05, "high": 0.15, "critical": 0.25}[risk_level]
            if risk_level in {"high", "critical"}:
                reasons.append(f"extraction marked {risk_level} risk")
        conf = float(req.get("confidence_score", 0.5))
        if conf < 0.5:
            score += 0.15
            reasons.append("low extraction confidence")
        if compliance_by_id.get(req["id"], {}).get("escalated"):
            score += 0.15
            reasons.append("compliance mapping needs human review")
        severe = [f for f in security_by_id.get(req["id"], []) if f.get("severity") in {"high", "critical"}]
        if severe:
            score += 0.20
            reasons.append("high-severity security/privacy finding")
        score = min(1.0, score)
        level = "critical" if score >= 0.80 else "high" if score >= 0.60 else "medium" if score >= 0.35 else "low"
        req["risk_level"] = level
        results.append({"requirement_id": req["id"], "risk_level": level, "score": round(score, 3), "rationale": "; ".join(reasons) or "No elevated risk indicators matched the configured rules."})
    state["risk_assessments"] = results
    state.setdefault("audit_events", []).append({"agent": "risk_analysis", "event": "rule_scoring_complete", "count": len(results)})
    return state
