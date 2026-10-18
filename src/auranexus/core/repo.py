"""Typed access to the store plus the hash-chained audit log."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..domain.models import (
    Checkpoint,
    Event,
    Notification,
    Project,
    Proposal,
    utcnow,
)
from .store import Doc, Store


def _jsonable(data: Any) -> Any:
    return json.loads(json.dumps(data, default=str))


def _dump(model: Any) -> Doc:
    return json.loads(model.model_dump_json())


def entry_hash(entry: Doc) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class AuditLog:
    """Append-only, per-tenant hash chain. Every agent action and human decision lands here."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def record(
        self,
        tenant_id: str,
        project_id: str | None,
        actor: str,
        actor_type: str,
        action: str,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
    ) -> Doc:
        def build(prev: Doc | None) -> Doc:
            entry: Doc = {
                "seq": (prev["seq"] + 1) if prev else 1,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "ts": utcnow().isoformat(),
                "actor": actor,
                "actor_type": actor_type,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "data": _jsonable(data or {}),
                "prev_hash": prev["hash"] if prev else "",
            }
            entry["hash"] = entry_hash(entry)
            return entry

        return self.store.append_audit(tenant_id, build)

    def verify(self, tenant_id: str) -> tuple[bool, int | None]:
        """Re-walk the chain. Returns (ok, first_bad_seq)."""
        prev_hash, expected_seq = "", 1
        for e in self.store.list_audit(tenant_id, limit=10**9):
            if e["seq"] != expected_seq or e["prev_hash"] != prev_hash or e["hash"] != entry_hash(e):
                return False, e["seq"]
            prev_hash, expected_seq = e["hash"], expected_seq + 1
        return True, None


class Repo:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.audit = AuditLog(store)

    # tenants (registry lives under the reserved tenant "_system")
    def register_tenant(self, tenant_id: str, name: str = "") -> None:
        self.store.put("tenants", "_system", tenant_id, {"id": tenant_id, "name": name or tenant_id})

    def list_tenants(self) -> list[str]:
        return [d["id"] for d in self.store.list("tenants", "_system")]

    # projects
    def put_project(self, p: Project) -> None:
        self.store.put("projects", p.tenant_id, p.id, _dump(p), p.id)

    def get_project(self, tenant_id: str, project_id: str) -> Project | None:
        d = self.store.get("projects", tenant_id, project_id)
        return Project.model_validate(d) if d else None

    def list_projects(self, tenant_id: str) -> list[Project]:
        return [Project.model_validate(d) for d in self.store.list("projects", tenant_id)]

    # events (idempotent processing marker)
    def claim_event(self, e: Event) -> bool:
        """True if this call is the first to see the event id."""
        if self.store.get("events", e.tenant_id, e.id):
            return False
        self.store.put("events", e.tenant_id, e.id, {**_dump(e), "status": "claimed"}, e.project_id)
        return True

    def finish_event(self, e: Event, status: str) -> None:
        self.store.put("events", e.tenant_id, e.id, {**_dump(e), "status": status}, e.project_id)

    # proposals / checkpoints
    def put_proposal(self, p: Proposal) -> None:
        self.store.put("proposals", p.tenant_id, p.id, _dump(p), p.project_id)

    def get_proposal(self, tenant_id: str, pid: str) -> Proposal | None:
        d = self.store.get("proposals", tenant_id, pid)
        return Proposal.model_validate(d) if d else None

    def list_proposals(self, tenant_id: str, project_id: str | None = None, **filters: Any) -> list[Proposal]:
        return [Proposal.model_validate(d) for d in self.store.list("proposals", tenant_id, project_id, filters)]

    def put_checkpoint(self, c: Checkpoint) -> None:
        self.store.put("checkpoints", c.tenant_id, c.id, _dump(c), c.project_id)

    def cas_checkpoint(self, c: Checkpoint) -> bool:
        """Optimistic update keyed on ``rev`` so concurrent decisions cannot both win."""
        return self.store.put_if("checkpoints", c.tenant_id, c.id, _dump(c), {"rev": c.rev - 1}, c.project_id)

    def get_checkpoint(self, tenant_id: str, cid: str) -> Checkpoint | None:
        d = self.store.get("checkpoints", tenant_id, cid)
        return Checkpoint.model_validate(d) if d else None

    def list_checkpoints(self, tenant_id: str, project_id: str | None = None, **filters: Any) -> list[Checkpoint]:
        return [Checkpoint.model_validate(d) for d in self.store.list("checkpoints", tenant_id, project_id, filters)]

    # register: approved, human-decided artifacts only (written by appliers)
    def register_put(self, tenant_id: str, project_id: str, kind: str, id: str, data: Doc) -> Doc:
        doc = {**_jsonable(data), "id": id, "kind": kind, "project_id": project_id, "tenant_id": tenant_id}
        self.store.put("register", tenant_id, f"{kind}:{id}", doc, project_id)
        return doc

    def register_get(self, tenant_id: str, kind: str, id: str) -> Doc | None:
        return self.store.get("register", tenant_id, f"{kind}:{id}")

    def register_list(self, tenant_id: str, project_id: str, kind: str | None = None) -> list[Doc]:
        return self.store.list("register", tenant_id, project_id, {"kind": kind} if kind else None)

    # reports: informational agent output, never treated as a decision
    def report_put(self, tenant_id: str, project_id: str, kind: str, id: str, data: Doc) -> Doc:
        doc = {**_jsonable(data), "id": id, "kind": kind, "project_id": project_id, "tenant_id": tenant_id}
        self.store.put("reports", tenant_id, f"{kind}:{id}", doc, project_id)
        return doc

    def report_list(self, tenant_id: str, project_id: str, kind: str | None = None) -> list[Doc]:
        return self.store.list("reports", tenant_id, project_id, {"kind": kind} if kind else None)

    # misc
    def put_run(self, tenant_id: str, project_id: str, run: Doc) -> None:
        self.store.put("agent_runs", tenant_id, run["id"], _jsonable(run), project_id)

    def list_runs(self, tenant_id: str, project_id: str | None = None) -> list[Doc]:
        return self.store.list("agent_runs", tenant_id, project_id)

    def put_notification(self, n: Notification) -> None:
        self.store.put("notifications", n.tenant_id, n.id, _dump(n), n.project_id)

    def list_notifications(self, tenant_id: str, project_id: str | None = None) -> list[Doc]:
        return self.store.list("notifications", tenant_id, project_id)

    def get_member_roles(self, tenant_id: str, email: str) -> list[str]:
        d = self.store.get("members", tenant_id, email.lower())
        return list(d.get("roles", [])) if d else []

    def put_member(self, tenant_id: str, email: str, roles: list[str]) -> None:
        self.store.put("members", tenant_id, email.lower(), {"email": email.lower(), "roles": roles})
