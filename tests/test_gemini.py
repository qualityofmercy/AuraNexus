"""Gemini-on-Vertex client behaviour with a stubbed google-genai client (no network)."""

from types import SimpleNamespace as NS

import pytest

from auranexus.config import Settings
from auranexus.core.llm import (
    AGENT_OUTPUT_SCHEMA,
    FakeLLM,
    GeminiVertexClient,
    LLMError,
    LLMRefusal,
    build_llm,
    gemini_schema,
)


class StubModels:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def generate_content(self, **kw):
        self.calls.append(kw)
        return self.resp


def client(resp, **settings):
    models = StubModels(resp)
    c = GeminiVertexClient(Settings(llm_backend="gemini", gcp_project="p", **settings), client=NS(models=models))
    return c, models


def resp(text='{"items": [], "open_questions": [], "notes": ""}', finish="STOP", block=None):
    return NS(text=text, prompt_feedback=NS(block_reason=block) if block else None,
              candidates=[NS(finish_reason=finish)], usage_metadata=NS(prompt_token_count=11, candidates_token_count=7))


def test_request_uses_json_schema_system_prompt_and_default_model():
    c, models = client(resp())
    out = c.generate_json(system="SYS", user="USER", schema=AGENT_OUTPUT_SCHEMA)
    call = models.calls[0]
    cfg = call["config"]
    assert call["model"] == "gemini-2.5-pro" and call["contents"] == "USER"
    assert cfg.system_instruction == "SYS" and cfg.response_mime_type == "application/json" and cfg.temperature == 0.0
    assert "additionalProperties" not in str(cfg.response_json_schema)
    assert cfg.response_json_schema["properties"]["items"]["items"]["required"]  # required fields kept
    assert (out.input_tokens, out.output_tokens, out.model) == (11, 7, "gemini-2.5-pro")


def test_model_is_configurable():
    c, models = client(resp(), model="gemini-custom-id")
    c.generate_json(system="s", user="u", schema={"type": "object"})
    assert models.calls[0]["model"] == "gemini-custom-id"


def test_code_fences_are_tolerated():
    c, _ = client(resp('```json\n{"items": [], "open_questions": [], "notes": "x"}\n```'))
    assert c.generate_json(system="s", user="u", schema={}).data["notes"] == "x"


@pytest.mark.parametrize("finish", ["SAFETY", "FinishReason.PROHIBITED_CONTENT", "BLOCKLIST"])
def test_safety_stops_are_refusals(finish):
    c, _ = client(resp(finish=finish, text=None))
    with pytest.raises(LLMRefusal):
        c.generate_json(system="s", user="u", schema={})


def test_blocked_prompt_is_a_refusal():
    c, _ = client(resp(block="SAFETY"))
    with pytest.raises(LLMRefusal):
        c.generate_json(system="s", user="u", schema={})


def test_truncation_empty_and_invalid_json_are_errors():
    for r in (resp(finish="MAX_TOKENS"), resp(text=None), resp(text="{not json")):
        c, _ = client(r)
        with pytest.raises(LLMError) as ei:
            c.generate_json(system="s", user="u", schema={})
        assert not isinstance(ei.value, LLMRefusal)


def test_schema_sanitiser_is_recursive_and_non_destructive():
    src = {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "array", "items": {"type": "object", "additionalProperties": False}}}}
    out = gemini_schema(src)
    assert "additionalProperties" not in str(out) and "additionalProperties" in str(src)


def test_backend_selection_and_defaults():
    assert isinstance(build_llm(Settings(llm_backend="fake")), FakeLLM)
    assert Settings(llm_backend="gemini").llm_model == "gemini-2.5-pro"
    assert Settings(llm_backend="claude").llm_model == "claude-sonnet-5-5"
    with pytest.raises(LLMError, match="GCP_PROJECT"):
        build_llm(Settings(llm_backend="gemini"))
    Settings(env="prod", auth_mode="oidc", store_backend="postgres", llm_backend="gemini").validate_for_runtime()
    with pytest.raises(RuntimeError):
        Settings(env="prod", auth_mode="oidc", store_backend="postgres", llm_backend="fake").validate_for_runtime()
