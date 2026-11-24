"""Shared JSON-only client for hosted and local LLM providers.

Compliance decisions still require retrieved evidence in compliance.py; this
client does not change that grounding requirement.
"""
from __future__ import annotations

import json
import re

import httpx

from app.config import settings

_FT_SYSTEM_PROMPT = '''You extract atomic, traceable software requirements from a stakeholder description for a personal/consumer loan application. Use only facts supported by the description. Do not invent thresholds, policies, regulations, integrations, or behaviors. Split distinct behaviors into separate requirements. Return only JSON with this shape: {"requirements":[{"slot":"one of the supplied source slots or one_shot_description/unmapped","statement":"The system shall ...","category":["valid category"],"priority":"low|medium|high|critical","acceptance_criteria":["observable criterion"],"confidence_score":0.0}],"sdlc_factor_inputs":{"expected_frequency_of_change":"explicit fact or empty string","regulatory_audit_criticality":"explicit fact or empty string","existing_system_integrations":"explicit fact or empty string","timeline_and_budget":"explicit fact or empty string"}}. Keep requirements concise. If a factor was not explicitly stated, use an empty string rather than inferring it.'''


def call_llm_json(
    system: str,
    user: str,
    max_tokens: int = 1500,
    response_schema: dict | None = None,
) -> dict:
    """Call the configured provider and parse its response as a JSON object."""
    provider = settings.LLM_PROVIDER.strip().lower()
    if provider == "ollama":
        return _call_ollama(system, user, max_tokens)
    if provider == "gemini":
        return _call_gemini(system, user, max_tokens, response_schema)
    if provider == "anthropic":
        return _call_anthropic(system, user, max_tokens)
    if provider == "local_finetuned":
        return _call_colab_endpoint(system, user, max_tokens)
    raise ValueError(
        f"Unsupported LLM_PROVIDER {settings.LLM_PROVIDER!r}; use 'gemini', 'ollama', 'anthropic', or 'local_finetuned'."
    )


def _call_colab_endpoint(system: str, user: str, max_tokens: int) -> dict:
    marker = "Stakeholder brief:\n"
    description = user.split(marker, 1)[1] if marker in user else user
    colab_user = "Client description:\n" + description
    if not settings.HF_COLAB_ENDPOINT_URL:
        raise RuntimeError("HF_COLAB_ENDPOINT_URL is not set. Set it in backend/.env.")
    try:
        response = httpx.post(
            f"{settings.HF_COLAB_ENDPOINT_URL.rstrip('/')}/extract",
            json={"system": _FT_SYSTEM_PROMPT, "user": colab_user, "max_tokens": max_tokens},
            headers={"ngrok-skip-browser-warning": "true"},
            timeout=1200,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Colab endpoint returned HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Could not reach Colab endpoint: {exc}") from exc
    text = response.json().get("text", "")
    if not text.strip():
        raise ValueError("Colab endpoint returned empty output.")
    try:
        return _extract_json(text)
    except Exception as exc:
        raise ValueError(
            f"Colab model output was not valid JSON ({exc}). RAW OUTPUT START: {text[:700]!r}"
        ) from exc


def _call_ollama(system: str, user: str, max_tokens: int) -> dict:
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": settings.LLM_MODEL,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"num_predict": max_tokens, "temperature": 0.1},
    }
    try:
        response = httpx.post(url, json=payload, timeout=settings.OLLAMA_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise RuntimeError(
            "Cannot connect to Ollama at " + settings.OLLAMA_BASE_URL
            + ". Start Ollama and download the configured model with `ollama pull "
            + settings.LLM_MODEL + "`."
        ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise RuntimeError(
                f"Ollama model {settings.LLM_MODEL!r} is not available. Run `ollama pull {settings.LLM_MODEL}`."
            ) from exc
        raise RuntimeError(f"Ollama returned HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc

    body = response.json()
    content = body.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Ollama returned an empty message content.")
    return _extract_json(content)


def _call_anthropic(system: str, user: str, max_tokens: int) -> dict:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Set it in backend/.env to use Anthropic.")
    from anthropic import Anthropic

    response = Anthropic(api_key=settings.ANTHROPIC_API_KEY).messages.create(
        model=settings.LLM_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return _extract_json(text)


def _call_gemini(system: str, user: str, max_tokens: int, response_schema: dict | None = None) -> dict:
    if not settings.GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set. Add a Gemini API key to backend/.env.")
    url = (
        f"{settings.GEMINI_BASE_URL.rstrip('/')}/models/"
        f"{settings.LLM_MODEL}:generateContent"
    )
    generation_config = {
        "responseMimeType": "application/json",
        "maxOutputTokens": max_tokens,
    }
    if settings.LLM_MODEL.strip().lower().startswith("gemini-3"):
        # Gemini 3 defaults to high internal reasoning. Its thinking tokens
        # count against maxOutputTokens and can leave too little room for the
        # structured JSON this app needs. These extraction tasks need direct
        # schema following, so request low thinking and keep Gemini 3's default
        # temperature as recommended by Google's API guide.
        generation_config["thinkingConfig"] = {"thinkingLevel": "LOW"}
    else:
        generation_config["temperature"] = 0.1

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": generation_config,
    }
    if response_schema:
        payload["generationConfig"]["responseSchema"] = response_schema
    try:
        response = httpx.post(
            url,
            params={"key": settings.GOOGLE_API_KEY},
            json=payload,
            timeout=settings.OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise RuntimeError(f"Gemini API returned HTTP {exc.response.status_code}: {detail}") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Could not reach Gemini API: {exc}") from exc

    body = response.json()
    candidates = body.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text.strip():
        raise ValueError(
            f"Gemini returned no text content (finishReason={candidate.get('finishReason')}; "
            f"promptFeedback={body.get('promptFeedback', {})})."
        )
    try:
        return _extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        finish_reason = candidate.get("finishReason", "unknown")
        raise ValueError(f"Gemini returned invalid JSON (finishReason={finish_reason}): {exc}") from exc


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"LLM response was not parseable JSON: {text[:300]!r}")
        result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError("LLM response must be a JSON object.")
    return result
