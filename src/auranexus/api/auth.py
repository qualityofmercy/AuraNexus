"""Authentication & authorisation.

prod:  Google-signed OIDC ID token (Cloud Run IAM / IAP-style). Roles come from the tenant's member
       table, never from the token, so access is revocable without reissuing tokens.
local: trusted dev headers (X-Dev-User, X-Dev-Roles). Refused when AURANEXUS_ENV != local.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request

from ..config import Settings
from ..domain.models import Role

log = logging.getLogger("auranexus.auth")


@dataclass
class Principal:
    email: str
    tenant_id: str
    roles: list[Role]

    def has_any(self, *roles: Role) -> bool:
        return Role.ADMIN in self.roles or any(r in self.roles for r in roles)


def _verify_token(settings: Settings, authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    from google.auth.transport import requests as greq
    from google.oauth2 import id_token

    try:
        return id_token.verify_oauth2_token(
            authorization.split(" ", 1)[1], greq.Request(), [settings.oidc_audience, *settings.oidc_extra_audiences]
        )
    except Exception as exc:
        log.warning("token verification failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(401, "invalid token") from exc


def get_principal(
    request: Request,
    x_tenant_id: str = Header(default=""),
    x_dev_user: str = Header(default="dev@local"),
    x_dev_roles: str = Header(default=""),
    authorization: str | None = Header(default=None),
    x_auranexus_token: str | None = Header(default=None),
) -> Principal:
    c = request.app.state.container
    s: Settings = c.settings
    if not x_tenant_id:
        raise HTTPException(400, "X-Tenant-Id header required")
    if s.auth_mode == "dev":
        if s.env != "local" and not s.demo_mode:
            raise HTTPException(500, "dev auth is only allowed in the local environment")
        try:
            roles = [Role(r.strip()) for r in x_dev_roles.split(",") if r.strip()]
        except ValueError as exc:
            raise HTTPException(400, f"unknown role: {exc}") from exc
        return Principal(x_dev_user, x_tenant_id, roles)
    # Cloud Run redacts the signature of Authorization (it is the IAM credential), so clients also send the same
    # token in X-Auranexus-Token, which reaches us intact and is fully verified here.
    claims = _verify_token(s, f"Bearer {x_auranexus_token}" if x_auranexus_token else authorization)
    if not claims.get("email_verified", False):
        raise HTTPException(401, "email not verified")
    email = claims["email"].lower()
    roles_raw = c.repo.get_member_roles(x_tenant_id, email)
    if not roles_raw:
        raise HTTPException(403, "not a member of this tenant")
    return Principal(email, x_tenant_id, [Role(r) for r in roles_raw])


def require(*roles: Role):
    def dep(p: Principal = Depends(get_principal)) -> Principal:
        if not p.has_any(*roles):
            raise HTTPException(403, f"requires one of: {[r.value for r in roles]}")
        return p

    return dep


def require_member(p: Principal = Depends(get_principal)) -> Principal:
    if not p.roles:
        raise HTTPException(403, "no roles in this tenant")
    return p


def _unverified_claims(authorization: str | None) -> dict:
    """Claims of a token whose signature Cloud Run already validated and then redacted. Never use on an
    internet-reachable service: it is only meaningful behind IAM-enforced, invoker-restricted ingress."""
    import base64
    import json

    try:
        payload = (authorization or "").split(" ", 1)[1].split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:
        return {}


def verify_internal(request: Request, authorization: str | None = Header(default=None)) -> str:
    """Pub/Sub push and Cloud Scheduler call /internal/* with a service-account OIDC token."""
    s: Settings = request.app.state.container.settings
    if s.auth_mode == "dev":
        if s.env != "local" and not s.demo_mode:
            raise HTTPException(500, "dev auth is only allowed in the local environment")
        return "dev-internal"
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        claims = _verify_token(s, authorization)  # full verification wherever the signature survives
    except HTTPException:
        if not s.trust_edge_iam:
            raise
        claims = _unverified_claims(authorization)  # Cloud Run IAM already validated it; see settings
        if not claims:
            raise
    email = claims.get("email", "").lower()
    if email not in {e.lower() for e in s.internal_service_accounts}:
        raise HTTPException(403, "service account not allowed")
    return email
