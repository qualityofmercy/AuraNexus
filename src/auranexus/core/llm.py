"""LLM access. Production uses Gemini (default) or Claude on Vertex AI, both with schema-constrained JSON output."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import Settings


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    """The model declined (stop_reason == 'refusal'). Never retried automatically."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    raw: str = field(default="", repr=False)


class LLMClient(Protocol):
    def generate_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int | None = None
    ) -> LLMResult: ...


# Structured outputs require closed objects, so the free-form item payload travels as a JSON string.
EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "quote": {"type": "string"},
        "timestamp": {"type": "string"},
        "speaker": {"type": "string"},
        "source_ref": {"type": "string"},
    },
    "required": ["quote", "timestamp", "speaker", "source_ref"],
    "additionalProperties": False,
}

AGENT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "title": {"type": "string"},
                    "payload_json": {"type": "string", "description": "JSON object serialised as a string"},
                    "evidence": {"type": "array", "items": EVIDENCE_SCHEMA},
                    "confidence": {"type": "number"},
                    "inferred": {"type": "boolean"},
                },
                "required": ["kind", "title", "payload_json", "evidence", "confidence", "inferred"],
                "additionalProperties": False,
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["items", "open_questions", "notes"],
    "additionalProperties": False,
}


def normalise_agent_json(data: dict[str, Any]) -> dict[str, Any]:
    """Turn payload_json strings into payload dicts (tolerates already-parsed payloads)."""
    items = []
    for it in data.get("items", []):
        it = dict(it)
        raw = it.pop("payload_json", None)
        if raw is not None:
            try:
                it["payload"] = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (ValueError, TypeError):
                it["payload"] = {"_unparseable_payload": str(raw)[:2000]}
        items.append(it)
    return {**data, "items": items}


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
# JSON-Schema keywords outside the subset Vertex AI's Gemini structured output accepts.
_GEMINI_UNSUPPORTED = {"additionalProperties", "$schema", "$id", "$defs", "definitions"}


def gemini_schema(schema: Any) -> Any:
    """Strip keywords Gemini's response schema rejects. Closed-object semantics are enforced by our own
    pydantic validation (AgentOutput) and guardrails instead."""
    if isinstance(schema, dict):
        return {k: gemini_schema(v) for k, v in schema.items() if k not in _GEMINI_UNSUPPORTED}
    if isinstance(schema, list):
        return [gemini_schema(v) for v in schema]
    return schema


class GeminiVertexClient:
    """Gemini on Vertex AI via the google-genai SDK. Auth is ADC / the Cloud Run service account."""

    REFUSAL_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "RECITATION"}

    def __init__(self, settings: Settings, client: Any = None) -> None:
        self._settings = settings
        if client is not None:  # injected in tests
            self._client = client
            return
        from google import genai  # imported lazily: optional 'gcp' extra

        if not settings.gcp_project:
            raise LLMError("AURANEXUS_GCP_PROJECT is required for the gemini LLM backend")
        self._client = genai.Client(vertexai=True, project=settings.gcp_project, location=settings.vertex_region)

    def generate_json(self, *, system, user, schema, max_tokens=None) -> LLMResult:
        from google.genai import types

        s = self._settings
        resp = self._client.models.generate_content(
            model=s.llm_model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=gemini_schema(schema),
                max_output_tokens=max_tokens or s.max_output_tokens,
                temperature=s.temperature,
            ),
        )
        block = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
        if block:
            raise LLMRefusal(f"prompt blocked: {block}")
        cands = getattr(resp, "candidates", None) or []
        reason = str(getattr(cands[0], "finish_reason", "") or "") if cands else ""
        reason = reason.split(".")[-1].upper()  # enum or string -> "STOP", "MAX_TOKENS", ...
        if reason in self.REFUSAL_REASONS:
            raise LLMRefusal(f"model declined: finish_reason={reason}")
        if reason == "MAX_TOKENS":
            raise LLMError("model output truncated (MAX_TOKENS); reduce input or raise the limit")
        text = getattr(resp, "text", None)
        if not text:
            raise LLMError(f"model returned no content (finish_reason={reason or 'unknown'})")
        try:
            data = json.loads(_FENCE.sub("", text))
        except ValueError as e:
            raise LLMError(f"model returned invalid JSON: {e}") from e
        um = getattr(resp, "usage_metadata", None)
        return LLMResult(
            data=data,
            input_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(um, "candidates_token_count", 0) or 0),
            model=s.llm_model,
            raw=text,
        )


class VertexClaudeClient:
    """Claude on Vertex AI. Auth is ADC / the Cloud Run service account, no API key."""

    def __init__(self, settings: Settings) -> None:
        from anthropic import AnthropicVertex  # imported lazily: optional 'gcp' extra

        if not settings.gcp_project:
            raise LLMError("AURANEXUS_GCP_PROJECT is required for the vertex LLM backend")
        self._client = AnthropicVertex(project_id=settings.gcp_project, region=settings.vertex_region)
        self._settings = settings

    def generate_json(self, *, system, user, schema, max_tokens=None) -> LLMResult:
        s = self._settings
        resp = self._client.messages.create(
            model=s.llm_model,
            max_tokens=max_tokens or s.max_output_tokens,
            # Stable per-agent system prompt: cache it across runs.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": s.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "refusal":
            raise LLMRefusal(f"model refused: {getattr(resp, 'stop_details', None)}")
        if resp.stop_reason == "max_tokens":
            raise LLMError("model output truncated (max_tokens); reduce input or raise the limit")
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            data = json.loads(text)
        except ValueError as e:
            raise LLMError(f"model returned invalid JSON: {e}") from e
        return LLMResult(
            data=data,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=s.llm_model,
            raw=text,
        )


class FakeLLM:
    """Deterministic stand-in for tests and offline development."""

    def __init__(self, handler: Callable[[str, str], dict[str, Any]] | None = None) -> None:
        self.handler = handler or (lambda system, user: {"items": [], "open_questions": [], "notes": "fake"})
        self.calls: list[tuple[str, str]] = []

    def generate_json(self, *, system, user, schema, max_tokens=None) -> LLMResult:
        self.calls.append((system, user))
        return LLMResult(data=self.handler(system, user), model="fake")


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_backend == "gemini":
        return GeminiVertexClient(settings)
    if settings.llm_backend == "claude":
        return VertexClaudeClient(settings)
    return FakeLLM()
