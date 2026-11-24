"""Identify security/privacy requirements and notable control gaps."""
from app.config import settings
from app.graph.state import PipelineState
from app.llm.client import call_llm_json

_CONTROLS = {
    "authentication": ("authentication", "mfa", "multi-factor", "step-up"),
    "authorization": ("authorization", "role-based", "rbac", "least privilege"),
    "encryption": ("encrypt", "encryption", "tls", "at rest"),
    "data_protection": ("mask", "redact", "tokeniz", "data minimization"),
    "retention_and_deletion": ("retention", "delete", "purge", "retention period"),
    "auditability": ("audit log", "audit trail", "immutable log"),
}


def security_privacy_node(state: PipelineState) -> PipelineState:
    reqs = state.get("classified_requirements", [])
    if not settings.PHASE2_ENABLED or settings.STUB_MODE:
        state["security_privacy_findings"] = []
        state.setdefault("audit_events", []).append({"agent": "security_privacy", "event": "stub_noop"})
        return state
    findings = []
    text_by_req = [(r, r["statement"].lower() + " " + " ".join(r.get("category", [])).lower()) for r in reqs]
    covered = {name for name, terms in _CONTROLS.items() if any(any(term in body for term in terms) for _, body in text_by_req)}
    for req, body in text_by_req:
        if set(req.get("category", [])) & {"security", "privacy", "data-management", "audit-reporting"}:
            findings.append({"requirement_id": req["id"], "kind": "identified_control", "detail": req["statement"], "severity": "review"})
    gaps = [name for name in _CONTROLS if name not in covered]
    prompt = (
        "Review these consumer loan origination requirements for security/privacy threats or control gaps. "
        "Only report issues supported by the requirement text; distinguish stated requirements from recommendations. "
        "Return JSON only: {\"findings\":[{\"requirement_id\":\"id or null\",\"kind\":\"gap|risk\",\"detail\":\"...\",\"severity\":\"low|medium|high|critical\"}]}\n"
        f"Requirements: {[{'id': r['id'], 'statement': r['statement']} for r in reqs]}\nControl categories not explicit in the set: {gaps}"
    )
    try:
        result = call_llm_json("You are a security and privacy analyst for consumer lending software.", prompt)
        known = {r["id"] for r in reqs}
        for item in result.get("findings", []):
            if isinstance(item, dict) and (item.get("requirement_id") is None or item.get("requirement_id") in known):
                findings.append(item)
    except Exception as exc:
        state.setdefault("audit_events", []).append({"agent": "security_privacy", "event": "llm_error", "error": str(exc)[:300]})
    findings.extend({"requirement_id": None, "kind": "control_gap", "detail": f"No requirement explicitly addresses {gap.replace('_', ' ')}.", "severity": "high" if gap in {"authentication", "authorization", "encryption"} else "medium"} for gap in gaps)
    state["security_privacy_findings"] = findings
    state.setdefault("audit_events", []).append({"agent": "security_privacy", "event": "analysis_complete", "findings": len(findings), "control_gaps": gaps})
    return state
