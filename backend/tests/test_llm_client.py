"""
Unit tests for app/llm/client.py's JSON-extraction helper. These don't call
the network or need an API key — they just exercise the parsing logic that
every Phase 1+ LLM-backed node depends on to survive real-world model output
(markdown fences, stray leading/trailing prose).
"""
import pytest

from app.config import settings
from app.llm.client import _extract_json, call_sdlc_agent


def test_extracts_plain_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_strips_markdown_code_fence():
    text = '```json\n{"a": 1, "b": [1, 2, 3]}\n```'
    assert _extract_json(text) == {"a": 1, "b": [1, 2, 3]}


def test_strips_bare_code_fence_no_json_tag():
    text = '```\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_recovers_json_embedded_in_prose():
    text = 'Sure, here is the result:\n{"a": 1}\nLet me know if you need anything else.'
    assert _extract_json(text) == {"a": 1}


def test_raises_on_unparseable_text():
    with pytest.raises(ValueError):
        _extract_json("this is not json at all")


def test_sdlc_agent_routes_to_colab_sdlc_and_validates_response(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "local_finetuned")
    monkeypatch.setattr(settings, "HF_COLAB_ENDPOINT_URL", "https://example.ngrok.app/")
    ranking = [{"method": "Agile", "percentage": 73.5}]
    response_body = {
        "summary": "The methods reflect different trade-offs.",
        "per_method": [{"method": "Agile", "explanation": "Supports iterative delivery."}],
        "risks": ["Frequent scope changes may affect estimates."],
    }
    called = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return response_body

    def fake_post(url, **kwargs):
        called["url"] = url
        called["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)
    result = call_sdlc_agent(
        requirements=[{"statement": "The system shall support applications."}],
        ranking=ranking,
        project_summary="Consumer loan application",
    )

    assert called["url"] == "https://example.ngrok.app/sdlc"
    assert called["kwargs"]["json"]["ranking"] == ranking
    assert result == response_body


def test_sdlc_agent_rejects_invalid_response_shape(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "local_finetuned")
    monkeypatch.setattr(settings, "HF_COLAB_ENDPOINT_URL", "https://example.ngrok.app")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"summary": "Missing method explanations", "per_method": [], "risks": []}

    monkeypatch.setattr("app.llm.client.httpx.post", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(ValueError, match="methods must match"):
        call_sdlc_agent([], [{"method": "Agile", "percentage": 70.0}])
