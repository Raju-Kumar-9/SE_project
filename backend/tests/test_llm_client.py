"""
Unit tests for app/llm/client.py's JSON-extraction helper. These don't call
the network or need an API key — they just exercise the parsing logic that
every Phase 1+ LLM-backed node depends on to survive real-world model output
(markdown fences, stray leading/trailing prose).
"""
import pytest

from app.llm.client import _extract_json


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
