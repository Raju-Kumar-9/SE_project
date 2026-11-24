"""Ask one targeted follow-up at a time and revise requirements from answers."""
from app.config import settings
from app.graph.state import PipelineState
from app.llm.client import call_llm_json


def clarification_node(state: PipelineState) -> PipelineState:
    reqs = state.get("classified_requirements", [])
    pending = state.get("pending_clarification")

    # A pending question means this invocation contains the stakeholder's answer.
    if pending:
        answer = state.get("user_message", "").strip()
        if settings.PHASE2_ENABLED and not settings.STUB_MODE and answer:
            selected = [r for r in reqs if r["id"] in pending.get("requirement_ids", [])]
            prompt = (
                "Use the stakeholder's clarification only to resolve the identified issue. "
                "Preserve supported details and do not add unsupported facts. Return JSON only: "
                '{"updates":[{"id":"...","statement":"The system shall ...",'
                '"assumptions":["..."],"confidence_score":0.0}]}\nIssue: '
                + str(pending.get("question")) + "\nRequirements: " + str(selected) + "\nAnswer: " + answer
            )
            result = call_llm_json("You are a cautious requirements clarification agent.", prompt)
            updates = {u.get("id"): u for u in result.get("updates", []) if isinstance(u, dict)}
            for req in reqs:
                update = updates.get(req["id"])
                if update and update.get("statement"):
                    req["statement"] = str(update["statement"]).strip()
                    try:
                        req["confidence_score"] = min(1.0, max(0.0, float(update.get("confidence_score", req.get("confidence_score", 0.5)))))
                    except (TypeError, ValueError):
                        pass
                    req.setdefault("assumptions", []).extend(x for x in update.get("assumptions", []) if x not in req.get("assumptions", []))
        state["pending_clarification"] = None
        state["clarification_answer_pending"] = True
        state["clarification_rounds"] = int(state.get("clarification_rounds", 0)) + 1
        state.setdefault("audit_events", []).append({"agent": "clarification", "event": "answer_applied", "round": state["clarification_rounds"]})
        return state

    if not settings.PHASE2_ENABLED or settings.STUB_MODE:
        state["clarification_flags"] = []
        state["clarification_answer_pending"] = False
        state.setdefault("audit_events", []).append({"agent": "clarification", "event": "stub_noop", "flags": 0})
        return state

    rounds = int(state.get("clarification_rounds", 0))
    max_rounds = settings.CLARIFICATION_MAX_ROUNDS
    issues = [
        {"requirement_id": r["id"], "kind": "low_confidence", "detail": r["statement"]}
        for r in reqs if float(r.get("confidence_score", 1.0)) < 0.60
    ]
    issues.extend({"requirement_ids": c["requirement_ids"], "kind": c["kind"], "detail": c["explanation"]} for c in state.get("conflicts", []))
    try:
        quality = call_llm_json(
            "You are a requirements quality reviewer. Return JSON only.",
            "Identify requirements that are materially ambiguous, incomplete, or not testable from their wording. "
            "Do not flag merely missing implementation detail. Return {\"issues\":[{\"requirement_id\":\"...\",\"kind\":\"ambiguity|incomplete|not_testable\",\"detail\":\"...\"}]}. "
            f"Requirements: {[{'id': r['id'], 'statement': r['statement']} for r in reqs]}",
        )
        known = {r["id"] for r in reqs}
        for issue in quality.get("issues", []):
            if isinstance(issue, dict) and issue.get("requirement_id") in known:
                issues.append({"requirement_id": issue["requirement_id"], "kind": issue.get("kind", "quality"), "detail": str(issue.get("detail", ""))})
    except Exception as exc:
        state.setdefault("audit_events", []).append({"agent": "clarification", "event": "quality_check_error", "error": str(exc)[:300]})
    state["clarification_flags"] = issues
    state["clarification_answer_pending"] = False

    if issues and rounds < max_rounds:
        prompt = (
            "Choose the single most useful question to resolve one listed requirement issue. "
            "Ask a neutral, concise question to the loan product stakeholder. Return JSON only: "
            '{"question":"...","requirement_ids":["..."]}\nIssues: ' + str(issues) +
            "\nRequirements: " + str(reqs)
        )
        result = call_llm_json("You are the clarification agent for a consumer loan origination project.", prompt)
        ids = [i for i in result.get("requirement_ids", []) if any(r["id"] == i for r in reqs)]
        question = str(result.get("question", "")).strip()
        if question and ids:
            state["pending_clarification"] = {"question": question, "requirement_ids": ids, "issues": issues}
            state["assistant_message"] = question
            state.setdefault("audit_events", []).append({"agent": "clarification", "event": "follow_up_requested", "requirement_ids": ids})
            return state

    if issues:
        state.setdefault("escalations", []).append(f"{len(issues)} unresolved clarification issue(s) after {rounds} round(s); reviewer attention required")
    state["pending_clarification"] = None
    state.setdefault("audit_events", []).append({"agent": "clarification", "event": "clarification_complete", "flags": len(issues)})
    return state
