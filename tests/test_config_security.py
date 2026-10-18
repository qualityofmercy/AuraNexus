import pytest
from fastapi.testclient import TestClient

from auranexus.api.app import create_app
from auranexus.config import Settings
from auranexus.container import build_container
from auranexus.core.llm import AGENT_OUTPUT_SCHEMA, normalise_agent_json


def test_prod_refuses_unsafe_configuration():
    with pytest.raises(RuntimeError, match="auth_mode must be 'oidc'"):
        Settings(env="prod").validate_for_runtime()
    with pytest.raises(RuntimeError):
        build_container(Settings(env="prod", auth_mode="oidc"))  # memory store + fake LLM


def test_dev_header_auth_is_refused_outside_local():
    s = Settings(env="dev", auth_mode="dev")
    c = build_container(s)
    r = TestClient(create_app(s, c)).get("/v1/projects", headers={"X-Tenant-Id": "t", "X-Dev-Roles": "pm"})
    assert r.status_code == 500


def test_internal_endpoint_requires_allow_listed_identity():
    s = Settings(env="local", auth_mode="oidc", oidc_audience="x")
    client = TestClient(create_app(s, build_container(s)))
    assert client.post("/internal/pubsub/push", json={"message": {}}).status_code == 401
    assert client.post("/internal/pubsub/push", json={"message": {}}, headers={"Authorization": "Basic x"}).status_code == 401
    assert client.get("/v1/projects", headers={"X-Tenant-Id": "t"}).status_code == 401  # no token, no dev fallback


def test_missing_tenant_header_rejected(h):
    assert h.client("pm").get("/v1/projects", headers={"X-Tenant-Id": ""}).status_code == 400


def test_agent_schema_is_closed_and_payload_roundtrips():
    item = AGENT_OUTPUT_SCHEMA["properties"]["items"]["items"]
    assert item["additionalProperties"] is False and "payload_json" in item["required"]
    out = normalise_agent_json({"items": [{"kind": "k", "title": "t", "payload_json": '{"a": 1}', "evidence": [],
                                           "confidence": 0.5, "inferred": False}]})
    assert out["items"][0]["payload"] == {"a": 1}
    bad = normalise_agent_json({"items": [{"kind": "k", "title": "t", "payload_json": "{oops", "evidence": [],
                                           "confidence": 0.5, "inferred": False}]})
    assert "_unparseable_payload" in bad["items"][0]["payload"]


def test_human_record_revisions_keep_history(h):
    pm = h.client("pm")
    pm.post("/v1/projects/prj1/records/workshop", json={"id": "W1", "data": {"process_area": "O2C", "status": "planned"}})
    pm.post("/v1/projects/prj1/records/workshop", json={"id": "W1", "data": {"process_area": "O2C", "status": "held"}})
    doc = pm.get("/v1/projects/prj1/register", params={"kind": "workshop"}).json()[0]
    assert doc["status"] == "held" and doc["history"][0]["status"] == "planned"
