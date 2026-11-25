"""The SDLC agent may annotate deterministic scores but never replaces them."""
from app.config import settings
from app.graph.nodes import sdlc_selection


def _scored_result():
    ranking = [
        {"model": "Agile", "score": 0.72, "score_percent": 72.0},
        {"model": "Spiral", "score": 0.68, "score_percent": 68.0},
    ]
    factors = {
        "change_frequency": {
            "rating": 4,
            "scale": "1=low, 5=high",
            "rationale": "Test factor",
            "basis": "direct interview slot",
            "input_available": True,
        }
    }
    return {"ranked_scores": ranking, "factors_used": factors}, factors


def _state():
    requirements = [{"statement": "The system shall accept consumer loan applications.", "category": ["functional"]}]
    return {
        "classified_requirements": requirements,
        "extracted_requirements": requirements,
        "initial_description": "Consumer loan application",
        "audit_events": [],
    }


def _enable_agent(monkeypatch):
    monkeypatch.setattr(settings, "PHASE3_ENABLED", True)
    monkeypatch.setattr(settings, "SDLC_AGENT_ENABLED", True)
    monkeypatch.setattr(settings, "STUB_MODE", False)
    monkeypatch.setattr(settings, "PHASE3_NARRATION_ENABLED", False)
    monkeypatch.setattr(sdlc_selection, "score_project", lambda state: _scored_result())


def test_enabled_agent_stores_explanation_without_changing_scores(monkeypatch):
    _enable_agent(monkeypatch)
    analysis = {
        "summary": "Methods have different delivery and risk trade-offs.",
        "per_method": [
            {"method": "Agile", "explanation": "Supports iteration."},
            {"method": "Spiral", "explanation": "Emphasizes risk review."},
        ],
        "risks": ["Frequent change can affect planning."],
    }
    monkeypatch.setattr(sdlc_selection, "call_sdlc_agent", lambda **kwargs: analysis)

    result = sdlc_selection.sdlc_selection_node(_state())

    assert result["sdlc_recommendation"]["ranked_scores"] == _scored_result()[0]["ranked_scores"]
    assert result["sdlc_agent_analysis"] == analysis
    assert result["sdlc_recommendation"]["agent_analysis"] == analysis
    assert any(event["event"] == "sdlc_agent_analysis" for event in result["audit_events"])


def test_agent_exception_keeps_scores_and_stores_no_explanation(monkeypatch):
    _enable_agent(monkeypatch)

    def fail(**kwargs):
        raise TimeoutError("Colab request timed out")

    monkeypatch.setattr(sdlc_selection, "call_sdlc_agent", fail)
    result = sdlc_selection.sdlc_selection_node(_state())

    assert result["sdlc_recommendation"]["ranked_scores"] == _scored_result()[0]["ranked_scores"]
    assert result["sdlc_agent_analysis"] is None
    event = next(event for event in result["audit_events"] if event["event"] == "sdlc_agent_error")
    assert "timed out" in event["error"]


def test_invalid_agent_response_keeps_scores_and_stores_no_explanation(monkeypatch):
    _enable_agent(monkeypatch)
    monkeypatch.setattr(
        sdlc_selection,
        "call_sdlc_agent",
        lambda **kwargs: {"summary": "Incomplete", "per_method": [], "risks": []},
    )

    result = sdlc_selection.sdlc_selection_node(_state())

    assert result["sdlc_recommendation"]["ranked_scores"] == _scored_result()[0]["ranked_scores"]
    assert result["sdlc_agent_analysis"] is None
    event = next(event for event in result["audit_events"] if event["event"] == "sdlc_agent_error")
    assert "do not match" in event["error"]


def test_disabled_agent_makes_no_call_and_keeps_deterministic_scores(monkeypatch):
    monkeypatch.setattr(settings, "PHASE3_ENABLED", True)
    monkeypatch.setattr(settings, "SDLC_AGENT_ENABLED", False)
    monkeypatch.setattr(settings, "STUB_MODE", False)
    monkeypatch.setattr(settings, "PHASE3_NARRATION_ENABLED", False)
    monkeypatch.setattr(sdlc_selection, "score_project", lambda state: _scored_result())
    monkeypatch.setattr(
        sdlc_selection,
        "call_sdlc_agent",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("agent should be disabled")),
    )

    result = sdlc_selection.sdlc_selection_node(_state())

    assert result["sdlc_recommendation"]["ranked_scores"] == _scored_result()[0]["ranked_scores"]
    assert result["sdlc_agent_analysis"] is None
