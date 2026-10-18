"""AuraNexus HTTP API: ingest events, review and decide checkpoints, read the register, audit."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..container import Container, build_container
from ..core.bus import decode_push_envelope
from ..core.hitl import Conflict, HITLError, InvalidDecision, NotAuthorized
from ..domain.models import DecisionOutcome, Event, Phase, Project, ProjectType, Role, new_id, utcnow
from ..exports.xlsx import test_tracker_workbook
from ..orchestrator.router import TransientFailure
from ..tools.run import current_rubric_digest
from .auth import Principal, require, require_member, verify_internal

log = logging.getLogger("auranexus.api")

# Events a human or connector may submit. Everything else is internal (emitted by agents / HITL).
EXTERNAL_EVENTS = {
    "workshop.scheduled", "transcript.received", "schedule.weekly",
    "design.plan.requested", "design.workshop.scheduled", "design.transcript.received",
    "gate.design_readiness.requested", "gate.scope_freeze.requested",
    "scope.finalized", "scope.reviewed", "estimates.reviewed",
    "build.requirements.received", "fs.requested", "ts.requested", "review.requested", "tests.requested",
    "dod.requested", "change.requested", "cutover.review.requested", "schedule.sprint_end",
    "test.scripts.received", "test.assess.requested", "test.status.updated", "defect.changed", "transport.changed",
    "cutover.plan.requested", "rehearsal.actuals.updated", "rehearsal.notes.received", "rehearsal.completed",
    "ticket.received", "project.closed", "lessons.received", "quality.requested", "cutover.sync.requested",
}

# Human-authored records written directly (with audit): who may write them, and the event they trigger.
HUMAN_KINDS: dict[str, dict[str, Any]] = {
    "workshop": {"roles": [Role.PM, Role.FACILITATOR, Role.WORKSHOP_LEAD]},
    "signoff": {"roles": [Role.PM]},  # agents never record a sign-off
    "stakeholder": {"roles": [Role.PM]},
    "scope_disposition": {"roles": [Role.PM, Role.SOLUTION_ARCHITECT]},
    "ricefw_object": {"roles": [Role.FUNCTIONAL_LEAD, Role.TECHNICAL_LEAD, Role.PM]},
    "past_ricefw": {"roles": [Role.TECHNICAL_LEAD, Role.PM]},
    "transport": {"roles": [Role.TECHNICAL_LEAD]},
    "test_case": {"roles": [Role.TEST_LEAD, Role.TESTER], "event": "test.status.updated"},
    "defect": {"roles": [Role.TEST_LEAD, Role.TESTER, Role.TECHNICAL_LEAD]},
    "rehearsal": {"roles": [Role.CUTOVER_MANAGER, Role.CUTOVER_LEAD, Role.PM]},
    "rehearsal_task": {"roles": [Role.CUTOVER_LEAD, Role.CUTOVER_MANAGER], "event": "rehearsal.actuals.updated"},
    "reconciliation": {"roles": [Role.CUTOVER_LEAD, Role.TECHNICAL_LEAD]},
    "risk_log": {"roles": [Role.PM]},
    "glossary": {"roles": [Role.PM, Role.WORKSHOP_LEAD]},
    "reference_project": {"roles": [Role.PM, Role.DELIVERY_LEAD]},
    "roster": {"roles": [Role.PM, Role.DELIVERY_LEAD]},
    "integration": {"roles": [Role.SOLUTION_ARCHITECT, Role.PM]},
}


class ProjectIn(BaseModel):
    id: str | None = None
    name: str
    project_type: ProjectType
    settings: dict[str, Any] = Field(default_factory=dict)


class EventIn(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None  # client-supplied id makes submission idempotent


class RecordIn(BaseModel):
    id: str
    data: dict[str, Any] = Field(default_factory=dict)


class DecisionIn(BaseModel):
    outcome: DecisionOutcome
    reason: str = ""
    modified_payload: dict[str, Any] | None = None
    acting_role: Role | None = None


class MemberIn(BaseModel):
    email: str
    roles: list[Role]


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container or build_container(settings)
        yield

    app = FastAPI(title="AuraNexus", version="0.1.0", lifespan=lifespan)
    if container:  # tests build the app without running lifespan
        app.state.container = container

    def c(request: Request) -> Container:
        return request.app.state.container

    # ------------------------------------------------------------ health
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(request: Request) -> dict[str, Any]:
        ok = c(request).repo.store.ping()
        return {"status": "ready" if ok else "unavailable", "agents": len(c(request).registry.specs)}

    # ------------------------------------------------------------ tenants / members / projects
    @app.post("/v1/tenants", status_code=201)
    def create_tenant(body: MemberIn, request: Request, tenant_id: str, p: Principal = Depends(require(Role.ADMIN))) -> dict:
        """Bootstrap a tenant: registers it and its first member (use the platform admin identity)."""
        repo = c(request).repo
        repo.register_tenant(tenant_id)
        repo.put_member(tenant_id, body.email, [r.value for r in body.roles])
        repo.audit.record(tenant_id, None, p.email, "human", "tenant.created", "tenant", tenant_id, {"first_member": body.email})
        return {"tenant_id": tenant_id}

    @app.put("/v1/members")
    def put_member(body: MemberIn, request: Request, p: Principal = Depends(require(Role.ADMIN, Role.PM))) -> dict:
        if Role.ADMIN in body.roles and Role.ADMIN not in p.roles:
            raise HTTPException(403, "only an admin can grant admin")
        repo = c(request).repo
        repo.put_member(p.tenant_id, body.email, [r.value for r in body.roles])
        repo.audit.record(p.tenant_id, None, p.email, "human", "member.updated", "member", body.email.lower(),
                          {"roles": [r.value for r in body.roles]})
        return {"email": body.email.lower(), "roles": body.roles}

    @app.post("/v1/projects", status_code=201)
    def create_project(body: ProjectIn, request: Request, p: Principal = Depends(require(Role.PM))) -> Project:
        repo = c(request).repo
        proj = Project(id=body.id or new_id("prj_"), tenant_id=p.tenant_id, name=body.name,
                       project_type=body.project_type, settings=body.settings)
        if repo.get_project(p.tenant_id, proj.id):
            raise HTTPException(409, "project exists")
        repo.register_tenant(p.tenant_id)
        repo.put_project(proj)
        repo.audit.record(p.tenant_id, proj.id, p.email, "human", "project.created", "project", proj.id,
                          {"project_type": proj.project_type.value})
        return proj

    @app.get("/v1/projects")
    def list_projects(request: Request, p: Principal = Depends(require_member)) -> list[Project]:
        return c(request).repo.list_projects(p.tenant_id)

    def project_or_404(request: Request, p: Principal, project_id: str) -> Project:
        proj = c(request).repo.get_project(p.tenant_id, project_id)
        if not proj:
            raise HTTPException(404, "project not found")
        return proj

    @app.put("/v1/projects/{project_id}/phase")
    def set_phase(project_id: str, phase: Phase, request: Request, p: Principal = Depends(require(Role.PM))) -> Project:
        proj = project_or_404(request, p, project_id)
        proj.phase = phase
        c(request).repo.put_project(proj)
        c(request).repo.audit.record(p.tenant_id, proj.id, p.email, "human", "project.phase_set", "project", proj.id, {"phase": phase.value})
        return proj

    # ------------------------------------------------------------ events
    @app.post("/v1/projects/{project_id}/events", status_code=202)
    def submit_event(project_id: str, body: EventIn, request: Request, p: Principal = Depends(require_member)) -> dict:
        project_or_404(request, p, project_id)
        if p.roles == [Role.VIEWER]:
            raise HTTPException(403, "viewers cannot submit events")
        if body.type not in EXTERNAL_EVENTS:
            raise HTTPException(422, f"event type '{body.type}' cannot be submitted externally")
        ev = Event(tenant_id=p.tenant_id, project_id=project_id, type=body.type, payload=body.payload, **({"id": body.id} if body.id else {}))
        c(request).repo.audit.record(p.tenant_id, project_id, p.email, "human", "event.submitted", "event", ev.id, {"type": ev.type})
        c(request).bus.publish(ev)
        return {"event_id": ev.id}

    @app.post("/v1/projects/{project_id}/records/{kind}", status_code=201)
    def write_record(project_id: str, kind: str, body: RecordIn, request: Request, p: Principal = Depends(require_member)) -> dict:
        project_or_404(request, p, project_id)
        spec = HUMAN_KINDS.get(kind)
        if not spec:
            raise HTTPException(422, f"'{kind}' cannot be written directly; it is produced via agent proposals and approval")
        if not p.has_any(*spec["roles"]):
            raise HTTPException(403, f"requires one of: {[r.value for r in spec['roles']]}")
        repo = c(request).repo
        prev = repo.register_get(p.tenant_id, kind, body.id)
        history = []
        if prev:  # revisions never destroy the earlier version
            history = [*prev.get("history", []), {k: v for k, v in prev.items() if k != "history"}]
        doc = repo.register_put(p.tenant_id, project_id, kind, body.id,
                                {**body.data, "recorded_by": p.email, "history": history})
        repo.audit.record(p.tenant_id, project_id, p.email, "human", "record.revised" if prev else "record.written",
                          kind, body.id, {"revision": len(history) + 1})
        if spec.get("event"):
            payload = {"test_id": body.id, "status": body.data.get("status"), "actor": p.email,
                       "produced": body.data.get("produced", {})} if kind == "test_case" else {"task_id": body.id, "rehearsal_id": body.data.get("rehearsal_id")}
            c(request).bus.publish(Event(tenant_id=p.tenant_id, project_id=project_id, type=spec["event"], payload=payload))
        return doc

    # ------------------------------------------------------------ read models
    @app.get("/v1/projects/{project_id}/register")
    def get_register(project_id: str, request: Request, kind: str | None = None, p: Principal = Depends(require_member)) -> list[dict]:
        project_or_404(request, p, project_id)
        return c(request).repo.register_list(p.tenant_id, project_id, kind)

    @app.get("/v1/projects/{project_id}/reports")
    def get_reports(project_id: str, request: Request, kind: str | None = None, p: Principal = Depends(require_member)) -> list[dict]:
        project_or_404(request, p, project_id)
        return c(request).repo.report_list(p.tenant_id, project_id, kind)

    @app.get("/v1/projects/{project_id}/proposals")
    def get_proposals(project_id: str, request: Request, status: str | None = None, kind: str | None = None,
                      p: Principal = Depends(require_member)) -> list:
        project_or_404(request, p, project_id)
        f = {k: v for k, v in {"status": status, "kind": kind}.items() if v}
        return c(request).repo.list_proposals(p.tenant_id, project_id, **f)

    @app.get("/v1/projects/{project_id}/runs")
    def get_runs(project_id: str, request: Request, p: Principal = Depends(require_member)) -> list[dict]:
        project_or_404(request, p, project_id)
        return c(request).repo.list_runs(p.tenant_id, project_id)

    @app.get("/v1/projects/{project_id}/notifications")
    def get_notifications(project_id: str, request: Request, p: Principal = Depends(require_member)) -> list[dict]:
        project_or_404(request, p, project_id)
        return c(request).repo.list_notifications(p.tenant_id, project_id)

    @app.post("/v1/notifications/{notification_id}/release")
    def release_notification(notification_id: str, request: Request,
                             p: Principal = Depends(require(Role.PM, Role.TEST_LEAD, Role.CUTOVER_MANAGER))) -> dict:
        """Agents draft; a human releases anything that is not an auto-send handoff."""
        repo = c(request).repo
        d = repo.store.get("notifications", p.tenant_id, notification_id)
        if not d:
            raise HTTPException(404, "notification not found")
        if d["status"] != "drafted":
            raise HTTPException(409, f"notification is {d['status']}")
        from ..domain.models import Notification

        n = Notification.model_validate({**d, "status": "sent"})
        repo.put_notification(n)
        c(request).bus.publish_notification(n)
        repo.audit.record(p.tenant_id, n.project_id, p.email, "human", "notification.released", "notification", n.id, {})
        return {"id": n.id, "status": n.status}

    # ------------------------------------------------------------ HITL
    @app.get("/v1/checkpoints")
    def list_checkpoints(request: Request, project_id: str | None = None, p: Principal = Depends(require_member)) -> list[dict]:
        return c(request).orchestrator.open_checkpoints(p.tenant_id, project_id)

    @app.get("/v1/checkpoints/{checkpoint_id}")
    def get_checkpoint(checkpoint_id: str, request: Request, p: Principal = Depends(require_member)) -> dict:
        repo = c(request).repo
        cp = repo.get_checkpoint(p.tenant_id, checkpoint_id)
        if not cp:
            raise HTTPException(404, "checkpoint not found")
        return {"checkpoint": cp, "proposal": repo.get_proposal(p.tenant_id, cp.proposal_id)}

    @app.post("/v1/checkpoints/{checkpoint_id}/decision")
    def decide(checkpoint_id: str, body: DecisionIn, request: Request, p: Principal = Depends(require_member)) -> dict:
        try:
            prop = c(request).hitl.decide(p.tenant_id, checkpoint_id, p.email, p.roles, body.outcome, body.reason,
                                          body.modified_payload, body.acting_role)
        except NotAuthorized as e:
            raise HTTPException(403, str(e)) from e
        except Conflict as e:
            raise HTTPException(409, str(e)) from e
        except InvalidDecision as e:
            raise HTTPException(422, str(e)) from e
        except HITLError as e:
            raise HTTPException(404, str(e)) from e
        return {"proposal_id": prop.id, "status": prop.status}

    # ------------------------------------------------------------ audit & governance
    @app.get("/v1/projects/{project_id}/audit")
    def get_audit(project_id: str, request: Request, limit: int = 500,
                  p: Principal = Depends(require(Role.PM, Role.STEERING, Role.ADMIN))) -> list[dict]:
        project_or_404(request, p, project_id)
        return c(request).repo.store.list_audit(p.tenant_id, project_id, min(limit, 5000))

    @app.get("/v1/audit/verify")
    def verify_audit(request: Request, p: Principal = Depends(require(Role.PM, Role.ADMIN))) -> dict:
        ok, bad = c(request).repo.audit.verify(p.tenant_id)
        return {"ok": ok, "first_bad_seq": bad}

    @app.post("/v1/projects/{project_id}/rubric/freeze")
    def freeze_rubric(project_id: str, request: Request, p: Principal = Depends(require(Role.PM))) -> dict:
        """(Re)freeze the cutover scoring rubric. The first scored rehearsal freezes it automatically;
        later changes need this explicit, audited PM decision."""
        proj = project_or_404(request, p, project_id)
        cont = c(request)
        digest, info = current_rubric_digest(cont.settings.config_dir, proj.project_type.value)
        doc = cont.repo.register_put(p.tenant_id, project_id, "rubric_freeze", f"rf-{digest}",
                                     {"hash": digest, **info, "frozen_by": p.email, "status": "frozen",
                                      "frozen_at": utcnow().isoformat()})
        cont.repo.audit.record(p.tenant_id, project_id, p.email, "human", "rubric.frozen", "rubric", digest, info)
        return doc

    @app.get("/v1/projects/{project_id}/exports/test-tracker.xlsx")
    def export_tracker(project_id: str, request: Request, p: Principal = Depends(require_member)) -> Response:
        project_or_404(request, p, project_id)
        cases = c(request).repo.register_list(p.tenant_id, project_id, "test_case")
        data = test_tracker_workbook(cases)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{project_id}-test-tracker.xlsx"'})

    if settings.enable_internal:
        # ------------------------------------------------------------ internal (Pub/Sub push, Scheduler)
        @app.post("/internal/pubsub/push", status_code=204)
        def pubsub_push(body: dict, request: Request, _: str = Depends(verify_internal)) -> Response:
            data = decode_push_envelope(body)
            attrs = data.pop("_attributes", {})
            cont = c(request)
            try:
                if data.get("type", "").startswith("schedule.") and not data.get("tenant_id"):
                    cont.orchestrator.fan_out_schedule(data["type"])
                elif data.get("tenant_id") and data.get("type"):
                    cont.orchestrator.handle(Event.model_validate(data))
                else:
                    log.warning("ignoring malformed push message attrs=%s", attrs)
            except TransientFailure as exc:
                log.error("transient failure, requesting redelivery: %s", exc)
                raise HTTPException(503, "transient agent failure") from exc
            return Response(status_code=204)


    return app

