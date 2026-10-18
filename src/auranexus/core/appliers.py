"""Appliers: the ONLY code that writes decided artifacts into the register.

An applier runs after a checkpoint is finally approved. Agents never call these directly.
Each returns the list of ``(event_type, payload)`` follow-on events to publish.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.models import Decision, Proposal, utcnow
from .repo import Repo

Emitted = list[tuple[str, dict[str, Any]]]


@dataclass
class ApplyContext:
    repo: Repo
    proposal: Proposal
    payload: dict[str, Any]  # approved payload (the modified one when a human edited it)
    decisions: list[Decision]  # approving decisions

    @property
    def approvers(self) -> list[str]:
        return [d.decided_by for d in self.decisions]

    def put(self, kind: str, id: str, data: dict[str, Any]) -> dict[str, Any]:
        p = self.proposal
        return self.repo.register_put(
            p.tenant_id,
            p.project_id,
            kind,
            id,
            {
                **data,
                "source_proposal_id": p.id,
                "decided_by": self.approvers,
                "decided_at": utcnow().isoformat(),
            },
        )


Applier = Callable[[ApplyContext], Emitted]
RejectHandler = Callable[[ApplyContext, Decision], Emitted]

_APPLIERS: dict[str, Applier] = {}
_ON_REJECT: dict[str, RejectHandler] = {}


def applier(*kinds: str) -> Callable[[Applier], Applier]:
    def deco(fn: Applier) -> Applier:
        for k in kinds:
            _APPLIERS[k] = fn
        return fn

    return deco


def on_reject(*kinds: str) -> Callable[[RejectHandler], RejectHandler]:
    def deco(fn: RejectHandler) -> RejectHandler:
        for k in kinds:
            _ON_REJECT[k] = fn
        return fn

    return deco


def apply_proposal(ctx: ApplyContext) -> Emitted:
    return _APPLIERS.get(ctx.proposal.kind, _default)(ctx)


def reject_proposal(ctx: ApplyContext, decision: Decision) -> Emitted:
    handler = _ON_REJECT.get(ctx.proposal.kind)
    emitted = handler(ctx, decision) if handler else []
    # Rejections are learning data (Template Steward watches this pattern).
    ctx.repo.register_put(
        ctx.proposal.tenant_id,
        ctx.proposal.project_id,
        "rejection",
        ctx.proposal.id,
        {
            "rejected_kind": ctx.proposal.kind,
            "agent_id": ctx.proposal.agent_id,
            "reason": decision.reason,
            "title": ctx.proposal.title,
            "rejected_by": decision.decided_by,
            "decided_at": utcnow().isoformat(),
        },
    )
    return [*emitted, ("rejection.recorded", {"proposal_id": ctx.proposal.id, "kind": ctx.proposal.kind})]


def _entity_id(ctx: ApplyContext) -> str:
    return str(ctx.payload.get("id") or ctx.proposal.id)


def _default(ctx: ApplyContext) -> Emitted:
    ctx.put(
        ctx.proposal.kind,
        _entity_id(ctx),
        {
            **ctx.payload,
            "status": "approved",
            "title": ctx.proposal.title,
            "evidence": [e.model_dump() for e in ctx.proposal.evidence],
            "inferred": ctx.proposal.inferred,
            "confidence": ctx.proposal.confidence,
            "validated": True,
        },
    )
    return []


@applier("requirement_entry", "requirement")
def _requirement(ctx: ApplyContext) -> Emitted:
    ctx.put(
        ctx.proposal.kind,
        _entity_id(ctx),
        {
            **ctx.payload,
            "status": "validated",
            "validated": True,
            "title": ctx.proposal.title,
            "evidence": [e.model_dump() for e in ctx.proposal.evidence],
            "inferred": ctx.proposal.inferred,
            "confidence": ctx.proposal.confidence,
        },
    )
    return []


# ---- template stewardship (Prepare) ----------------------------------------------------------

_MAJOR_CHANGES = {"split_column", "rename", "retire"}


def _bump(version: str, major: bool) -> str:
    m = re.match(r"^v?(\d+)\.(\d+)$", version)
    ma, mi = (int(m.group(1)), int(m.group(2))) if m else (1, 0)
    return f"v{ma + 1}.0" if major else f"v{ma}.{mi + 1}"


@applier("template_change")
def _template_change(ctx: ApplyContext) -> Emitted:
    p = ctx.proposal
    versions = sorted(ctx.repo.register_list(p.tenant_id, p.project_id, "template_version"), key=lambda d: d["seq"])
    current = versions[-1]["version"] if versions else "v1.0"
    major = ctx.payload.get("change_type") in _MAJOR_CHANGES
    new = _bump(current, major)
    ctx.put(
        "template_version",
        new,
        {
            "seq": len(versions) + 1,
            "version": new,
            "previous": current,
            "major": major,
            "changes": [ctx.payload],
            "reason": ctx.payload.get("reason", ""),
            "affected_workshops": ctx.payload.get("affected_workshops", []),
            "affected_entries": ctx.payload.get("affected_entries", 0),
            "status": "approved",
        },
    )
    return [("template.version_changed", {"version": new, "major": major})]


# ---- consolidation (Prepare) -----------------------------------------------------------------


@applier("merge_proposal")
def _merge(ctx: ApplyContext) -> Emitted:
    p = ctx.proposal
    master_id = str(ctx.payload.get("master_id") or ctx.proposal.id)
    sources = [str(s) for s in ctx.payload.get("source_ids", [])]
    ctx.put(
        "requirement_entry",
        master_id,
        {**ctx.payload.get("master", {}), "status": "validated", "validated": True, "merged_from": sources},
    )
    for sid in sources:  # originals stay visible, only linked
        doc = ctx.repo.register_get(p.tenant_id, "requirement_entry", sid)
        if doc:
            ctx.repo.register_put(p.tenant_id, p.project_id, "requirement_entry", sid, {**doc, "duplicate_of": master_id})
    return []


@applier("conflict")
def _conflict(ctx: ApplyContext) -> Emitted:
    ctx.put("conflict", _entity_id(ctx), {**ctx.payload, "status": "open", "owner": ctx.payload.get("owner", "")})
    return []


@applier("conflict_resolution")
def _conflict_resolution(ctx: ApplyContext) -> Emitted:
    p = ctx.proposal
    cid = str(ctx.payload.get("conflict_id", ""))
    if not ctx.payload.get("owner") or not ctx.payload.get("resolution"):
        raise ValueError("a conflict is only closed with a recorded decision and an owner")
    doc = ctx.repo.register_get(p.tenant_id, "conflict", cid)
    if doc:
        ctx.repo.register_put(
            p.tenant_id,
            p.project_id,
            "conflict",
            cid,
            {**doc, "status": "resolved", "resolution": ctx.payload["resolution"], "owner": ctx.payload["owner"]},
        )
    return []


# ---- cross-team flags (Prepare / Design) -----------------------------------------------------


@applier("cross_team_flag", "sentinel_flag")
def _flag(ctx: ApplyContext) -> Emitted:
    fid = _entity_id(ctx)
    ctx.put(ctx.proposal.kind, fid, {**ctx.payload, "status": "raised", "title": ctx.proposal.title})
    # Accepting a flag creates a workshop request (human then schedules it).
    ctx.put(
        "workshop_request",
        f"wr-{fid}",
        {
            "target_area": ctx.payload.get("target_area") or ctx.payload.get("area_affected"),
            "reason": ctx.payload.get("why") or ctx.payload.get("reason"),
            "suggested_attendee": ctx.payload.get("suggested_attendee", ""),
            "flag_id": fid,
            "status": "open",
        },
    )
    return [("workshop.requested", {"flag_id": fid})]


@on_reject("cross_team_flag", "sentinel_flag")
def _flag_dismissed(ctx: ApplyContext, decision: Decision) -> Emitted:
    ctx.repo.register_put(
        ctx.proposal.tenant_id,
        ctx.proposal.project_id,
        ctx.proposal.kind,
        _entity_id(ctx),
        {**ctx.payload, "status": "dismissed", "dismissal_reason": decision.reason},
    )
    return []


# ---- reports requiring sign-off --------------------------------------------------------------


@applier("weekly_summary")
def _weekly_summary(ctx: ApplyContext) -> Emitted:
    ctx.put("weekly_summary", _entity_id(ctx), {**ctx.payload, "status": "published"})
    return [("summary.published", {"id": _entity_id(ctx)})]


@applier("rebaseline_decision")
def _rebaseline(ctx: ApplyContext) -> Emitted:
    ctx.put("rebaseline", _entity_id(ctx), {**ctx.payload, "status": "ordered"})
    return [("rebaseline.ordered", {"id": _entity_id(ctx)})]


# ---- cutover plan / task changes (Build, Test, Run) ------------------------------------------


@applier("cutover_task_change", "cutover_plan_update")
def _cutover_change(ctx: ApplyContext) -> Emitted:
    p = ctx.proposal
    task_id = str(ctx.payload.get("task_id") or ctx.payload.get("cutover_task_id") or "")
    if not task_id:
        raise ValueError("cutover change requires task_id")
    existing = ctx.repo.register_get(p.tenant_id, "cutover_task", task_id) or {}
    changes = dict(ctx.payload.get("changes") or {})
    state = ctx.payload.get("state") or ("New" if not existing else "Changed")
    version = int(existing.get("version", 0)) + 1
    log = list(existing.get("change_log", []))
    log.append(
        {
            "version": version,
            "proposal_id": p.id,
            "changes": changes,
            "reason": ctx.payload.get("reason", ""),
            "evidence": [e.model_dump() for e in p.evidence],
            "approved_by": ctx.approvers,
            "date": utcnow().isoformat(),
        }
    )
    ctx.put(
        "cutover_task",
        task_id,
        {**existing, **changes, "task_id": task_id, "state": state, "version": version, "change_log": log},
    )
    return [("cutover.task_changed", {"task_id": task_id, "state": state})]


# ---- guideline library (Build learning loop, Run guideline steward) ---------------------------


@applier("guideline_change", "refinement_proposal")
def _guideline(ctx: ApplyContext) -> Emitted:
    p = ctx.proposal
    target = ctx.payload.get("target", "guideline")
    # "Re-inject into the scope backlog": human-approved reinstatement of previously dropped requirements.
    for req in ctx.payload.get("reinstate_requirements", []) or []:
        ctx.put("requirement_entry", str(req["id"]), {
            **req, "status": "reinstated", "validated": True, "reinstated_by_proposal": p.id,
            "title": req.get("title") or req.get("as_is", "")[:80]})
    if target != "guideline":  # plan change: recorded, applied to the plan by the cutover team
        ctx.put("plan_change", _entity_id(ctx), {**ctx.payload, "status": "approved"})
        return [("plan.change_approved", {"id": _entity_id(ctx)})]
    versions = sorted(ctx.repo.register_list(p.tenant_id, p.project_id, "guideline_version"), key=lambda d: d["seq"])
    current = versions[-1]["version"] if versions else "1.0.0"
    ma, mi, pa = (int(x) for x in current.split("."))
    new = f"{ma}.{mi + 1}.0" if ctx.payload.get("change_type") != "wording" else f"{ma}.{mi}.{pa + 1}"
    ctx.put(
        "guideline_version",
        new,
        {
            "seq": len(versions) + 1,
            "version": new,
            "previous": current,
            "proposal_id": p.id,
            "change": ctx.payload,
            "approvers": ctx.approvers,
            "status": "approved",
        },
    )
    return [("guideline.version_published", {"version": new})]


# ---- test tracker ---------------------------------------------------------------------------


@applier("test_tracker")
def _tracker(ctx: ApplyContext) -> Emitted:
    rows = ctx.payload.get("rows", [])
    for row in rows:
        ctx.put("test_case", str(row["test_id"]), {**row, "status": row.get("status", "Not Started")})
    return [("test.tracker.created", {"count": len(rows)})]
