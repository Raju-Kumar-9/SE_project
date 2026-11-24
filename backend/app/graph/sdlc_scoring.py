"""Pure-Python, deterministic multi-criteria SDLC scoring."""
from __future__ import annotations

from typing import Any

FACTOR_WEIGHTS = {
    "requirement_stability": 1.0,
    "regulatory_criticality": 1.4,
    "security_risk": 1.3,
    "complexity": 1.0,
    "legacy_dependence": 0.8,
    "change_frequency": 1.1,
    "continuous_delivery_need": 0.8,
    "testing_documentation_need": 1.1,
    "schedule_budget_pressure": 0.8,
}

# Ideal factor rating (1=low, 5=high) for each process. Suitability for a
# factor is 5 - abs(project rating - model ideal), giving a 1..5 contribution.
MODEL_IDEALS = {
    "Agile": {"requirement_stability": 2, "regulatory_criticality": 3, "security_risk": 3, "complexity": 3, "legacy_dependence": 2, "change_frequency": 5, "continuous_delivery_need": 4, "testing_documentation_need": 3, "schedule_budget_pressure": 4},
    "DevSecOps": {"requirement_stability": 3, "regulatory_criticality": 4, "security_risk": 5, "complexity": 3, "legacy_dependence": 2, "change_frequency": 4, "continuous_delivery_need": 5, "testing_documentation_need": 5, "schedule_budget_pressure": 3},
    "Spiral": {"requirement_stability": 2, "regulatory_criticality": 4, "security_risk": 5, "complexity": 5, "legacy_dependence": 4, "change_frequency": 3, "continuous_delivery_need": 2, "testing_documentation_need": 4, "schedule_budget_pressure": 2},
    "V-Model": {"requirement_stability": 5, "regulatory_criticality": 5, "security_risk": 4, "complexity": 3, "legacy_dependence": 4, "change_frequency": 1, "continuous_delivery_need": 1, "testing_documentation_need": 5, "schedule_budget_pressure": 2},
    "Waterfall": {"requirement_stability": 5, "regulatory_criticality": 4, "security_risk": 2, "complexity": 2, "legacy_dependence": 4, "change_frequency": 1, "continuous_delivery_need": 1, "testing_documentation_need": 5, "schedule_budget_pressure": 2},
    "Agile + DevSecOps Hybrid": {"requirement_stability": 3, "regulatory_criticality": 5, "security_risk": 5, "complexity": 4, "legacy_dependence": 4, "change_frequency": 4, "continuous_delivery_need": 4, "testing_documentation_need": 5, "schedule_budget_pressure": 3},
}


def _slot(state: dict[str, Any], name: str) -> str:
    item = state.get("slot_state", {}).get(name, {})
    return str(item.get("value") or "") if isinstance(item, dict) else ""


def _rating(text: str, *, high_terms: tuple[str, ...], low_terms: tuple[str, ...], default: int = 3) -> int:
    value = text.lower()
    if any(term in value for term in low_terms):
        return 1
    if any(term in value for term in high_terms):
        return 5
    if any(term in value for term in ("moderate", "medium", "some", "occasionally")):
        return 3
    return default


def derive_factors(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reqs = state.get("classified_requirements") or state.get("extracted_requirements", [])
    all_text = " ".join(str(r.get("statement", "")) for r in reqs).lower()
    categories = {label for req in reqs for label in req.get("category", [])}
    frequency = _slot(state, "expected_frequency_of_change")
    audit = _slot(state, "regulatory_audit_criticality")
    legacy = _slot(state, "existing_system_integrations")
    timeline = _slot(state, "timeline_and_budget")

    change = _rating(frequency, high_terms=("daily", "weekly", "frequent", "rapid", "constant", "continuous", "often"), low_terms=("rare", "stable", "infrequent", "once", "never"), default=3)
    stability = 6 - change
    regulatory = _rating(audit, high_terms=("critical", "strict", "heavily", "high", "mandatory", "regulated"), low_terms=("low", "minimal", "not critical", "light"), default=4 if "regulatory" in categories else 3)
    security_count = sum(1 for label in categories if label in {"security", "privacy", "data-management"})
    security = min(5, max(2, 2 + security_count + (1 if any(t in all_text for t in ("biometric", "identity", "sensitive", "financial data", "fraud")) else 0)))
    integration_count = sum(1 for req in reqs if "integration" in req.get("category", []))
    complexity = min(5, max(1, 1 + len(reqs) // 5 + integration_count // 2 + sum(1 for t in ("multiple systems", "real-time", "automated decision", "machine learning", "legacy") if t in all_text)))
    legacy_rating = _rating(legacy, high_terms=("legacy", "mainframe", "multiple", "complex", "custom integration", "many systems"), low_terms=("none", "no existing", "standalone", "greenfield"), default=2 if not legacy else 3)
    delivery = 5 if any(t in all_text or t in frequency.lower() for t in ("continuous delivery", "continuous deployment", "ci/cd", "daily release")) else (4 if change >= 4 else 2 if change <= 2 else 3)
    testing_docs = min(5, max(2, 2 + (2 if regulatory >= 4 else 0) + (1 if "audit-reporting" in categories else 0) + (1 if "security" in categories else 0)))
    pressure = _rating(timeline, high_terms=("urgent", "aggressive", "tight", "short deadline", "limited budget", "cost-constrained"), low_terms=("flexible", "ample", "no fixed deadline", "well-funded"), default=3)

    values = {
        "requirement_stability": (stability, "Inferred as the inverse of stated change frequency.", bool(frequency)),
        "regulatory_criticality": (regulatory, "Derived from the audit-criticality slot and regulatory classifications.", bool(audit) or "regulatory" in categories),
        "security_risk": (security, "Derived from security/privacy categories and requirement content.", bool(reqs)),
        "complexity": (complexity, "Estimated from requirement volume, integrations, and complexity signals.", bool(reqs)),
        "legacy_dependence": (legacy_rating, "Derived from the existing-systems integration slot.", bool(legacy)),
        "change_frequency": (change, "Derived from the expected-frequency-of-change slot.", bool(frequency)),
        "continuous_delivery_need": (delivery, "Derived from explicit delivery language and expected change frequency.", bool(reqs) or bool(frequency)),
        "testing_documentation_need": (testing_docs, "Derived from regulatory, security, and audit requirements.", bool(reqs)),
        "schedule_budget_pressure": (pressure, "Derived from the timeline-and-budget slot.", bool(timeline)),
    }
    direct_slots = {"requirement_stability": bool(frequency), "regulatory_criticality": bool(audit),
                    "legacy_dependence": bool(legacy), "change_frequency": bool(frequency),
                    "schedule_budget_pressure": bool(timeline)}
    return {
        name: {
            "rating": rating,
            "scale": "1=low, 5=high",
            "rationale": rationale,
            "basis": "direct interview slot" if direct_slots.get(name) else ("derived from requirements or related slots" if available else "default; source input missing"),
            "input_available": available,
        }
        for name, (rating, rationale, available) in values.items()
    }


def score_sdlc_models(factors: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    total_weight = sum(FACTOR_WEIGHTS.values())
    ranked = []
    for model, ideals in MODEL_IDEALS.items():
        weighted = sum(FACTOR_WEIGHTS[factor] * (5 - abs(int(factors[factor]["rating"]) - ideals[factor])) for factor in FACTOR_WEIGHTS)
        percent = round(weighted / (total_weight * 5) * 100, 1)
        ranked.append({"model": model, "score": percent / 100, "score_percent": percent})
    return sorted(ranked, key=lambda row: (-row["score_percent"], row["model"]))


def score_project(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    factors = derive_factors(state)
    ranked = score_sdlc_models(factors)
    return {"ranked_scores": ranked, "factors_used": factors}, factors
