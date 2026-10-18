"""Cloud Run redacts the signature of Authorization JWTs it validated. These tests pin how we cope with that."""

import base64
import json

from fastapi.testclient import TestClient

from auranexus.api.app import create_app
from auranexus.config import Settings
from auranexus.container import build_container

PUSH_SA = "auranexus-pubsub-dev@proj.iam.gserviceaccount.com"


def redacted_token(email: str) -> str:
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{b({'alg': 'RS256'})}.{b({'email': email, 'email_verified': True})}.REDACTED-SIGNATURE-27-CHRS"


def push_body() -> dict:
    return {"message": {"data": base64.b64encode(b'{"type": "schedule.weekly"}').decode(), "attributes": {}}}


def client(**kw) -> TestClient:
    s = Settings(env="local", auth_mode="oidc", oidc_audience="x", internal_service_accounts=[PUSH_SA], **kw)
    return TestClient(create_app(s, build_container(s)))


def test_worker_trusts_edge_iam_claims_but_still_checks_the_allowlist():
    c = client(trust_edge_iam=True)
    ok = c.post("/internal/pubsub/push", json=push_body(), headers={"Authorization": f"Bearer {redacted_token(PUSH_SA)}"})
    assert ok.status_code == 204
    other = c.post("/internal/pubsub/push", json=push_body(),
                   headers={"Authorization": f"Bearer {redacted_token('someone-else@proj.iam.gserviceaccount.com')}"})
    assert other.status_code == 403
    assert c.post("/internal/pubsub/push", json=push_body(), headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_without_trust_flag_a_redacted_token_is_rejected():
    c = client(trust_edge_iam=False)
    r = c.post("/internal/pubsub/push", json=push_body(), headers={"Authorization": f"Bearer {redacted_token(PUSH_SA)}"})
    assert r.status_code == 401


def test_api_service_has_no_internal_routes():
    c = client(trust_edge_iam=False, enable_internal=False)
    assert c.post("/internal/pubsub/push", json=push_body()).status_code == 404


def test_user_api_never_trusts_unsigned_claims():
    """Even with the flag on, user endpoints require a fully verified token (taken from X-Auranexus-Token)."""
    c = client(trust_edge_iam=True)
    h = {"X-Tenant-Id": "acme", "Authorization": f"Bearer {redacted_token('pm@acme.com')}"}
    assert c.get("/v1/projects", headers=h).status_code == 401
    assert c.get("/v1/projects", headers={**h, "X-Auranexus-Token": redacted_token("pm@acme.com")}).status_code == 401
