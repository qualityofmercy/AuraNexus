"""Human-in-the-loop service. The single gate between agent proposals and the register.

Rules enforced in code:
  * agents only ever create Proposals + Checkpoints; the register is written by appliers after approval
  * only humans holding an approver role may decide; viewers/admins never decide (separation of duties)
  * modify / reject / defer require a written reason
  * tier-3 changes need multiple distinct approvers (and distinct roles)
  * a reject is a veto; deferral extends the deadline; overdue checkpoints escalate
  * every transition is written to the hash-chained audit log
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from ..domain.models import (
    Checkpoint,
    CheckpointStatus,
    Decision,
    DecisionOutcome,
    Event,
    Proposal,
    ProposalStatus,
    Role,
    utcnow,
)
from .analytics import AnalyticsSink, NullSink
from .appliers import ApplyContext, apply_proposal, reject_proposal
from .bus import EventBus
from .repo import Repo


class HITLError(Exception):
    pass


class NotAuthorized(HITLError):
    pass


class Conflict(HITLError):
    pass


class InvalidDecision(HITLError):
    pass


class HITLPolicy:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.tiers: dict[int, dict[str, Any]] = {int(k): v for k, v in data["tiers"].items()}

    @classmethod
    def load(cls, path: Path) -> HITLPolicy:
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    def tier(self, n: int) -> dict[str, Any]:
        return self.tiers[max(1, min(3, n))]

    @property
    def cannot_decide(self) -> set[str]:
        return set(self.data.get("cannot_decide", []))

    @property
    def reason_required(self) -> set[str]:
        return set(self.data.get("reason_required_for", []))

    def escalation_roles(self, level: int) -> list[str]:
        return list(self.data["escalation"]["roles_by_level"].get(level, []))


class HITLService:
    def __init__(
        self,
        repo: Repo,
        policy: HITLPolicy,
        bus: EventBus,
        clock: Callable[[], datetime] = utcnow,
        analytics: AnalyticsSink | None = None,
    ) -> None:
        self.repo, self.policy, self.bus, self.clock = repo, policy, bus, clock
        self.analytics = analytics or NullSink()

    # ------------------------------------------------------------------ submit
    def submit(
        self,
        proposal: Proposal,
        checkpoint_code: str,
        approver_roles: list[Role],
        tier: int | None = None,
    ) -> Proposal:
        tier = tier or proposal.tier
        tp = self.policy.tier(tier)
        roles = approver_roles or [Role(r) for r in tp.get("approver_roles", [])]
        if tp.get("approver_roles"):  # tier policy roles are added to the skill's roles
            roles = list(dict.fromkeys([*roles, *[Role(r) for r in tp["approver_roles"]]]))
        cp = Checkpoint(
            tenant_id=proposal.tenant_id,
            project_id=proposal.project_id,
            code=checkpoint_code,
            proposal_id=proposal.id,
            approver_roles=roles,
            tier=tier,
            required_approvals=int(tp.get("required_approvals", 1)),
            due_at=self.clock() + timedelta(hours=float(tp["due_hours"])),
            source_event_id=proposal.source_event_id,
        )
        proposal = proposal.model_copy(update={"tier": tier, "checkpoint_id": cp.id, "status": ProposalStatus.PENDING})
        self.repo.put_proposal(proposal)
        self.repo.put_checkpoint(cp)
        self.repo.audit.record(
            proposal.tenant_id,
            proposal.project_id,
            proposal.agent_id,
            "agent",
            "proposal.created",
            "proposal",
            proposal.id,
            {"kind": proposal.kind, "checkpoint": cp.id, "code": checkpoint_code, "tier": tier, "flags": proposal.flags},
        )
        return proposal

    def record_draft(self, proposal: Proposal) -> Proposal:
        """Informational output (checkpoint: none). Never enters the register as a decision."""
        proposal = proposal.model_copy(update={"status": ProposalStatus.DRAFT})
        self.repo.put_proposal(proposal)
        self.repo.audit.record(
            proposal.tenant_id, proposal.project_id, proposal.agent_id, "agent", "draft.created", "proposal",
            proposal.id, {"kind": proposal.kind},
        )
        return proposal

    # ------------------------------------------------------------------ decide
    def decide(
        self,
        tenant_id: str,
        checkpoint_id: str,
        user: str,
        user_roles: list[Role],
        outcome: DecisionOutcome,
        reason: str = "",
        modified_payload: dict[str, Any] | None = None,
        acting_role: Role | None = None,
    ) -> Proposal:
        cp = self.repo.get_checkpoint(tenant_id, checkpoint_id)
        if cp is None:
            raise HITLError("checkpoint not found")
        if cp.status != CheckpointStatus.OPEN:
            raise Conflict("checkpoint already decided")
        proposal = self.repo.get_proposal(tenant_id, cp.proposal_id)
        if proposal is None:
            raise HITLError("proposal not found")

        role = self._authorise(cp, user, user_roles, acting_role)
        if outcome.value in self.policy.reason_required and not reason.strip():
            raise InvalidDecision(f"a written reason is required to {outcome.value}")
        if outcome == DecisionOutcome.MODIFY and not modified_payload:
            raise InvalidDecision("modify requires modified_payload")

        decision = Decision(
            outcome=outcome, reason=reason, decided_by=user, role=role, modified_payload=modified_payload,
            decided_at=self.clock(),
        )
        cp.rev += 1

        if outcome == DecisionOutcome.DEFER:
            cp.due_at = self.clock() + timedelta(hours=float(self.policy.data.get("defer_hours", 72)))
            self._cas(cp)
            proposal.status = ProposalStatus.DEFERRED
            self.repo.put_proposal(proposal)
            self._audit_decision(proposal, cp, decision)
            return proposal

        if outcome == DecisionOutcome.REJECT:
            cp.status, cp.decision = CheckpointStatus.DECIDED, decision
            self._cas(cp)
            ctx = ApplyContext(self.repo, proposal, proposal.payload, [])
            events = reject_proposal(ctx, decision)
            proposal.status = ProposalStatus.REJECTED
            self.repo.put_proposal(proposal)
            self._audit_decision(proposal, cp, decision)
            self._emit(proposal, events)
            self._maybe_batch_complete(proposal)
            return proposal

        # approve / modify: collect votes
        if any(a.decided_by == user for a in cp.approvals):
            raise Conflict("you have already approved this checkpoint")
        pol = self.policy.tier(cp.tier)
        if pol.get("distinct_roles") and any(a.role == role for a in cp.approvals):
            raise Conflict(f"tier {cp.tier} needs approvals from distinct roles; role {role.value} already approved")
        cp.approvals.append(decision)
        if len(cp.approvals) < cp.required_approvals:
            self._cas(cp)
            self._audit_decision(proposal, cp, decision, partial=True)
            return proposal

        payload = proposal.payload
        for a in cp.approvals:
            if a.outcome == DecisionOutcome.MODIFY and a.modified_payload:
                payload = a.modified_payload
        cp.status, cp.decision = CheckpointStatus.DECIDED, decision
        self._cas(cp)
        try:
            events = apply_proposal(ApplyContext(self.repo, proposal, payload, cp.approvals))
        except Exception as exc:  # re-open so the human can retry; nothing half-applied is left decided
            cp.rev += 1
            cp.status, cp.decision = CheckpointStatus.OPEN, None
            cp.approvals = cp.approvals[:-1]
            self._cas(cp)
            self.repo.audit.record(
                tenant_id, proposal.project_id, user, "human", "apply.failed", "proposal", proposal.id,
                {"error": str(exc)},
            )
            raise InvalidDecision(f"could not apply: {exc}") from exc
        proposal = proposal.model_copy(
            update={"status": ProposalStatus.APPLIED, "applied_at": self.clock(), "payload": payload}
        )
        self.repo.put_proposal(proposal)
        self._audit_decision(proposal, cp, decision)
        self._emit(proposal, [("proposal.applied", {"kind": proposal.kind, "proposal_id": proposal.id}),
                              (f"proposal.applied.{proposal.kind}", {"proposal_id": proposal.id}), *events])
        self._maybe_batch_complete(proposal)
        return proposal

    # ------------------------------------------------------------------ escalation
    def sweep(self, tenant_id: str) -> list[Checkpoint]:
        """Escalate overdue open checkpoints. Called by Cloud Scheduler via the orchestrator."""
        now, escalated = self.clock(), []
        max_level = int(self.policy.data["escalation"]["max_level"])
        ext = float(self.policy.data["escalation"]["deadline_extension_hours"])
        for cp in self.repo.list_checkpoints(tenant_id, status=CheckpointStatus.OPEN.value):
            if cp.due_at > now or cp.escalation_level >= max_level:
                continue
            cp.rev += 1
            cp.escalation_level += 1
            extra = [Role(r) for r in self.policy.escalation_roles(cp.escalation_level)]
            cp.approver_roles = list(dict.fromkeys([*cp.approver_roles, *extra]))
            cp.due_at = now + timedelta(hours=ext)
            if not self.repo.cas_checkpoint(cp):
                continue
            self.repo.audit.record(
                tenant_id, cp.project_id, "system", "system", "checkpoint.escalated", "checkpoint", cp.id,
                {"level": cp.escalation_level, "roles": [r.value for r in cp.approver_roles]},
            )
            self.bus.publish(
                Event(
                    tenant_id=tenant_id, project_id=cp.project_id, type="hitl.escalated",
                    payload={"checkpoint_id": cp.id, "level": cp.escalation_level, "code": cp.code},
                )
            )
            escalated.append(cp)
        return escalated

    # ------------------------------------------------------------------ internals
    def _authorise(self, cp: Checkpoint, user: str, user_roles: list[Role], acting_role: Role | None) -> Role:
        candidates = [r for r in user_roles if r.value not in self.policy.cannot_decide and r in cp.approver_roles]
        if acting_role is not None:
            if acting_role not in candidates:
                raise NotAuthorized(f"{user} cannot act as {acting_role.value} on this checkpoint")
            return acting_role
        if not candidates:
            raise NotAuthorized(
                f"{user} holds none of the approver roles {[r.value for r in cp.approver_roles]} for {cp.code}"
            )
        # Prefer a role that has not already voted (matters for tier-3 distinct-role rules).
        voted = {a.role for a in cp.approvals}
        return next((r for r in candidates if r not in voted), candidates[0])

    def _cas(self, cp: Checkpoint) -> None:
        if not self.repo.cas_checkpoint(cp):
            raise Conflict("checkpoint was modified concurrently; reload and retry")

    def _audit_decision(self, p: Proposal, cp: Checkpoint, d: Decision, partial: bool = False) -> None:
        if not partial:
            self.analytics.emit("hitl_decisions", {
                "ts": d.decided_at.isoformat(), "tenant_id": p.tenant_id, "project_id": p.project_id,
                "checkpoint": cp.code, "kind": p.kind, "agent_id": p.agent_id, "tier": cp.tier,
                "outcome": d.outcome.value, "role": d.role.value,
                "latency_hours": round((d.decided_at - cp.created_at).total_seconds() / 3600, 2),
                "escalation_level": cp.escalation_level})
            if d.outcome != DecisionOutcome.REJECT and p.kind in ("scorecard", "quality_score") and "total" in p.payload:
                self.analytics.emit("quality_scores", {
                    "ts": d.decided_at.isoformat(), "tenant_id": p.tenant_id, "project_id": p.project_id,
                    "subject_type": p.kind, "subject_id": str(p.payload.get("id") or p.id),
                    "total": p.payload["total"], "rating": p.payload.get("rating"),
                    "rubric_version": str(p.payload.get("rubric_version", ""))})
        self.repo.audit.record(
            p.tenant_id, p.project_id, d.decided_by, "human",
            f"checkpoint.{d.outcome.value}" + (".partial" if partial else ""),
            "checkpoint", cp.id,
            {"proposal_id": p.id, "kind": p.kind, "code": cp.code, "role": d.role.value, "reason": d.reason,
             "modified": bool(d.modified_payload), "approvals": len(cp.approvals), "required": cp.required_approvals},
        )

    def _emit(self, p: Proposal, events: list[tuple[str, dict[str, Any]]]) -> None:
        for etype, payload in events:
            self.bus.publish(
                Event(tenant_id=p.tenant_id, project_id=p.project_id, type=etype, payload=payload,
                      parent_id=p.source_event_id)
            )

    def _maybe_batch_complete(self, p: Proposal) -> None:
        """When every checkpoint born from one source event is decided, announce a validated batch."""
        if not p.source_event_id:
            return
        open_cps = [
            c for c in self.repo.list_checkpoints(p.tenant_id, p.project_id, status=CheckpointStatus.OPEN.value)
            if c.source_event_id == p.source_event_id
        ]
        if not open_cps:
            kinds = sorted({q.kind for q in self.repo.list_proposals(p.tenant_id, p.project_id)
                            if q.source_event_id == p.source_event_id})
            self.bus.publish(
                Event(tenant_id=p.tenant_id, project_id=p.project_id, type="register.batch_validated",
                      payload={"source_event_id": p.source_event_id, "kinds": kinds}, parent_id=p.source_event_id)
            )
