"""The orchestrator. Deliberately NOT a reasoning agent: it routes events to agents, tracks open human
checkpoints, fans out schedule ticks, and escalates decisions that waited too long.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agents.registry import SkillRegistry
from ..agents.runner import AgentRunner, RunResult
from ..config import Settings
from ..core.bus import EventBus
from ..core.hitl import HITLService
from ..core.repo import Repo
from ..domain.models import CheckpointStatus, Event

SCHEDULE_EVENTS = {"schedule.hourly", "schedule.weekly", "schedule.sprint_end"}


class TransientFailure(RuntimeError):
    """Raised after all agents ran when at least one failed in a retryable way (Pub/Sub redelivers)."""


@dataclass
class Dispatch:
    event_id: str
    runs: list[RunResult] = field(default_factory=list)
    skipped_reason: str = ""


class Orchestrator:
    def __init__(self, repo: Repo, hitl: HITLService, runner: AgentRunner, registry: SkillRegistry,
                 bus: EventBus, settings: Settings) -> None:
        self.repo, self.hitl, self.runner, self.registry, self.bus, self.settings = repo, hitl, runner, registry, bus, settings

    # -------------------------------------------------------------- events
    def handle(self, event: Event) -> Dispatch:
        d = Dispatch(event.id)
        if event.type in SCHEDULE_EVENTS and not event.project_id:
            self.fan_out_schedule(event.type)
            d.skipped_reason = "fanned_out"
            return d
        if event.depth > self.settings.max_event_depth:
            self.repo.audit.record(event.tenant_id, event.project_id, "orchestrator", "system", "event.dropped_depth",
                                   "event", event.id, {"type": event.type, "depth": event.depth})
            d.skipped_reason = "max_depth"
            return d
        project = self.repo.get_project(event.tenant_id, event.project_id)
        if project is None:
            self.repo.audit.record(event.tenant_id, event.project_id, "orchestrator", "system", "event.unknown_project",
                                   "event", event.id, {"type": event.type})
            d.skipped_reason = "unknown_project"
            return d
        existing = self.repo.store.get("events", event.tenant_id, event.id)
        if existing and existing.get("status") == "done":
            d.skipped_reason = "duplicate"
            return d
        if not existing:
            self.repo.claim_event(event)
        self.repo.audit.record(event.tenant_id, project.id, "orchestrator", "system", "event.received", "event", event.id,
                               {"type": event.type})
        transient = []
        carried = {event.payload["kind"]} if "kind" in event.payload else set(event.payload.get("kinds", []))
        for spec in self.registry.for_event(event.type):
            if spec.when_kinds and carried and not carried & set(spec.when_kinds):
                continue
            res = self.runner.run(spec, event, project)
            d.runs.append(res)
            if res.status == "failed" and res.transient:
                transient.append(res)
        self.repo.finish_event(event, "failed" if transient else "done")
        if transient:
            raise TransientFailure("; ".join(f"{r.agent_id}: {r.error}" for r in transient))
        return d

    def fan_out_schedule(self, event_type: str) -> int:
        """Scheduler messages carry no tenant: emit one event per active project of every tenant."""
        n = 0
        for tenant in self.repo.list_tenants():
            if event_type == "schedule.hourly":
                self.hitl.sweep(tenant)  # escalate overdue checkpoints
            for project in self.repo.list_projects(tenant):
                self.bus.publish(Event(tenant_id=tenant, project_id=project.id, type=event_type))
                n += 1
        return n

    # -------------------------------------------------------------- checkpoint tracking
    def open_checkpoints(self, tenant_id: str, project_id: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for c in self.repo.list_checkpoints(tenant_id, project_id, status=CheckpointStatus.OPEN.value):
            p = self.repo.get_proposal(tenant_id, c.proposal_id)
            rows.append({
                "checkpoint_id": c.id, "code": c.code, "tier": c.tier, "due_at": c.due_at.isoformat(),
                "overdue": c.due_at < self.hitl.clock(), "escalation_level": c.escalation_level,
                "approvals": f"{len(c.approvals)}/{c.required_approvals}",
                "approver_roles": [r.value for r in c.approver_roles],
                "proposal": {"id": c.proposal_id, "kind": p.kind if p else None, "title": p.title if p else None,
                             "agent": p.agent_id if p else None, "flags": p.flags if p else []},
            })
        return sorted(rows, key=lambda r: r["due_at"])
