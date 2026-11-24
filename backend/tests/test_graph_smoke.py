"""
Drives a simulated interview through all 17 slots and asserts the full
13-agent pipeline runs and produces schema-conformant output. No DB or API
keys required — this calls the compiled graph directly with a plain dict
state, one invocation per simulated user turn, exactly like the /chat router
does but without touching Postgres.

Good first thing to run after any change to graph.py or the node files:

    cd backend
    python -m pytest tests/test_graph_smoke.py -v
"""
import os

os.environ.setdefault("STUB_MODE", "true")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/loan_origination")

from app.graph.graph import compiled_graph  # noqa: E402
from app.graph.state import REQUIRED_SLOTS, new_slot_state  # noqa: E402


def _run_full_interview() -> dict:
    slot_state = new_slot_state()
    result_state: dict = {}

    for i, slot in enumerate(REQUIRED_SLOTS):
        state = {
            "session_id": "00000000-0000-0000-0000-000000000000",
            "user_message": f"answer #{i} for {slot}",
            "slot_state": slot_state,
            "turn_index": i,
        }
        result_state = compiled_graph.invoke(state)
        slot_state = result_state["slot_state"]

    return result_state


def test_full_pipeline_runs_and_produces_schema_conformant_output():
    result = _run_full_interview()

    assert result["interview_complete"] is True

    # every slot ended up filled
    assert all(entry["status"] == "filled" for entry in result["slot_state"].values())

    # requirement extraction produced one row per filled slot, schema-conformant
    requirements = result["classified_requirements"]
    assert len(requirements) == len(REQUIRED_SLOTS)
    required_keys = {
        "id", "statement", "category", "source_stakeholder", "business_justification",
        "priority", "dependencies", "assumptions", "acceptance_criteria",
        "applicable_regulations", "risk_level", "confidence_score", "approval_status",
        "source_slot",
    }
    for req in requirements:
        assert required_keys.issubset(req.keys())
        assert 0.0 <= req["confidence_score"] <= 1.0

    # every downstream agent ran and left its mark
    assert result["clarification_flags"] == []
    assert result["conflicts"] == []
    assert len(result["compliance_mappings"]) == len(requirements)
    assert result["security_privacy_findings"] == []
    assert len(result["risk_assessments"]) == len(requirements)
    assert result["sdlc_recommendation"]["ranked_scores"]
    assert result["generated_documents"]
    assert result["validation_notes"]
    assert len(result["approval_routing"]) == len(requirements)

    # audit trail recorded something from every one of the 13 agents
    agents_seen = {e["agent"] for e in result["audit_events"]}
    assert agents_seen == {
        "coordinator", "stakeholder_interaction", "requirement_extraction",
        "classification", "clarification", "conflict_detection", "compliance",
        "security_privacy", "risk_analysis", "sdlc_selection", "documentation",
        "validation", "human_approval",
    }


def test_interview_asks_one_question_per_missing_slot():
    slot_state = new_slot_state()
    state = {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "user_message": "we're building a digital-first personal loan product",
        "slot_state": slot_state,
        "turn_index": 0,
    }
    result = compiled_graph.invoke(state)

    assert result["interview_complete"] is False
    assert result["assistant_message"]  # a follow-up question was asked
    filled = [s for s, e in result["slot_state"].items() if e["status"] == "filled"]
    assert len(filled) == 1
