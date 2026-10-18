"""Prepare-phase tools: mandatory-field facts, workshop quality scoring, weekly summary, re-baseline."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import yaml

from ..domain.models import ProposalStatus
from .base import ToolContext, ToolOutput, det_tool, draft, filled, pct, pre_tool
from .scoring import load_rubric, weighted_total

ACTIVE = (ProposalStatus.PENDING, ProposalStatus.APPLIED, ProposalStatus.DEFERRED)


def template(ctx: ToolContext) -> dict[str, Any]:
    return yaml.safe_load((ctx.settings.config_dir / "templates" / "requirement_template.yaml").read_text("utf-8"))


@pre_tool("knowledge")
def knowledge(ctx: ToolContext) -> ToolOutput:
    """knowledge:<file> loads config/knowledge/<file>.yaml (interdependency_map, accelerator_library)."""
    path = ctx.settings.config_dir / "knowledge" / f"{ctx.arg}.yaml"
    return ToolOutput(facts={ctx.arg: yaml.safe_load(path.read_text("utf-8"))})


def entries(ctx: ToolContext) -> list[tuple[dict[str, Any], bool, Any]]:
    """(payload, validated, proposal) for every live requirement entry, from the proposal ledger."""
    out = []
    for p in ctx.proposals("requirement_entry", *ACTIVE):
        out.append((p.payload, p.status == ProposalStatus.APPLIED, p))
    return out


@pre_tool("mandatory_fields")
def mandatory_fields(ctx: ToolContext) -> ToolOutput:
    t = template(ctx)
    area = ctx.event.payload.get("process_area")
    rows = [e for e, _, _ in entries(ctx) if not area or e.get("process_area") == area]
    mand = t["mandatory"]
    empty = defaultdict(int)
    for e in rows:
        for f in mand:
            if not filled(e.get(f)):
                empty[f] += 1
    captured = [{"id": e.get("id"), "type": e.get("type"), "as_is": e.get("as_is")} for e in rows][:200]
    return ToolOutput(
        facts={
            "mandatory_fields": mand,
            "project_type_fields": t.get("project_type_fields", {}).get(ctx.project.project_type.value, []),
            "fields_empty_counts": dict(empty),
            "already_captured": captured,
            "entries_considered": len(rows),
        }
    )


def score_workshop(ctx: ToolContext, workshop: dict[str, Any]) -> dict[str, Any]:
    t = template(ctx)
    wid, area = workshop["id"], workshop.get("process_area", "default")
    mine = [(e, v, p) for e, v, p in entries(ctx) if e.get("workshop_id") == wid or p.source_event_id == workshop.get("transcript_event_id")]
    rejected = [p for p in ctx.proposals("requirement_entry", ProposalStatus.REJECTED) if p.payload.get("workshop_id") == wid]
    n = len(mine)
    mand = t["mandatory"]
    completeness = sum(sum(filled(e.get(f)) for f in mand) / len(mand) for e, _, _ in mine) / n * 100 if n else 0.0
    specificity = pct(sum(any(c.isdigit() for c in str(e.get("volume_frequency", ""))) for e, _, _ in mine), n, 0.0)
    traceable = sum(1 for e, _, p in mine if p.evidence and all(x.quote and x.speaker and x.timestamp for x in p.evidence) and filled(e.get("owner")))
    flags = [f for f in ctx.proposals("cross_team_flag") if f.payload.get("source_workshop") == wid]
    acted = sum(1 for f in flags if f.status in (ProposalStatus.APPLIED, ProposalStatus.REJECTED))
    required = t["required_roles_by_area"].get(area, t["required_roles_by_area"]["default"])
    present = set(workshop.get("attendee_roles", []))
    open_q = sum(1 for e, _, _ in mine if e.get("type") == "open_question")
    conflicts = [c for c in ctx.register("conflict") if c.get("status") == "open" and wid in c.get("workshop_ids", [])]
    dup_pending = [p for p in ctx.proposals("merge_proposal", ProposalStatus.PENDING) if wid in p.payload.get("workshop_ids", [])]
    scores = {
        "completeness": round(completeness, 1),
        "specificity": specificity,
        "cross_process_awareness": pct(acted, len(flags), 100.0),
        "traceability": pct(traceable, n, 0.0),
        "validation_rate": pct(sum(1 for _, v, _ in mine if v), n, 0.0),
        "stakeholder_coverage": pct(len(present & set(required)), len(required)),
        "open_question_ratio": round(100 - pct(open_q, n, 0.0), 1) if n else 0.0,
        "consistency": max(0.0, round(100 - pct(len(conflicts) + len(dup_pending), max(n, 1), 0.0), 1)),
    }
    rubric = load_rubric(ctx.settings.config_dir, "prepare_quality")
    total = weighted_total(scores, rubric["weights"])
    return {
        "workshop_id": wid,
        "process_area": area,
        "entries": n,
        "rejected": len(rejected),
        "scores": scores,
        "total": total,
        "rating": "Green" if total >= rubric["thresholds"]["green"] else "Amber" if total >= rubric["thresholds"]["amber"] else "Red",
        "missing_roles": sorted(set(required) - present),
    }


def rebaseline_check(ctx: ToolContext, scored: list[dict[str, Any]]) -> dict[str, Any] | None:
    cfg = load_rubric(ctx.settings.config_dir, "prepare_quality")["rebaseline"]
    versions = sorted(ctx.register("template_version"), key=lambda d: d["seq"])
    done = {r.get("template_version") for r in ctx.register("rebaseline")}
    pending = [v for v in versions if v["version"] not in done]
    total_entries = sum(s["entries"] for s in scored) or 1
    decided = sum(s["entries"] * s["scores"]["validation_rate"] / 100 for s in scored) + sum(s["rejected"] for s in scored)
    rejection_rate = pct(sum(s["rejected"] for s in scored), decided, 0.0)
    reasons, affected = [], set()
    for v in pending:
        if v.get("major"):
            reasons.append(f"major template version change to {v['version']}")
        if pct(v.get("affected_entries", 0), total_entries, 0.0) > cfg["restructured_entries_pct"]:
            reasons.append(f"{v['version']} restructures more than {cfg['restructured_entries_pct']}% of entries")
        if len(v.get("affected_workshops", [])) > cfg["new_mandatory_field_workshops"]:
            reasons.append(f"{v['version']} applies to more than {cfg['new_mandatory_field_workshops']} completed workshops")
        affected |= set(v.get("affected_workshops", []))
    if rejection_rate > cfg["rejection_rate_pct"]:
        reasons.append(f"validation rejection rate {rejection_rate}% exceeds {cfg['rejection_rate_pct']}%")
        affected |= {s["workshop_id"] for s in scored if s["rejected"]}
    if not reasons:
        return None
    workshops = {w["id"]: w for w in ctx.register("workshop")}
    hours = round(sum(float(workshops.get(w, {}).get("duration_hours", 2)) * 1.5 for w in affected), 1)
    return {
        "template_version": pending[-1]["version"] if pending else None,
        "triggers": reasons,
        "affected_workshops": sorted(affected),
        "estimated_reprocessing_hours": hours,
        "recommendation": "Re-listen to the recordings and repopulate the refined template for the affected workshops.",
    }


@det_tool("prepare_monitor")
def prepare_monitor(ctx: ToolContext) -> ToolOutput:
    workshops = ctx.register("workshop")
    scored = [score_workshop(ctx, w) for w in workshops if w.get("status") in ("held", "complete", None)]
    out = ToolOutput()
    for s in scored:
        out.reports.append({"kind": "workshop_quality", "id": s["workshop_id"], "data": s})
    by_area: dict[str, list[float]] = defaultdict(list)
    for s in scored:
        by_area[s["process_area"]].append(s["total"])
    reqs = [(e, v) for e, v, _ in entries(ctx)]
    flags = ctx.proposals("cross_team_flag")
    conflicts = [c for c in ctx.register("conflict") if c.get("status") == "open"]
    urgent = sorted(
        (e for e, _ in reqs if e.get("type") == "pain_point" and e.get("urgency") == "High"),
        key=lambda e: str(e.get("id")),
    )[:10]
    referenced = defaultdict(int)  # coverage gaps: areas mentioned by entries but with no workshop
    held_areas = {w.get("process_area") for w in workshops if w.get("status") != "planned"}
    for e, _ in reqs:
        for a in e.get("impacted_areas", []) or []:
            if a not in held_areas:
                referenced[a] += 1
    done = sum(1 for e, v in reqs if v and not e.get("duplicate_of") and not any(c.get("status") == "open" and e.get("id") in c.get("requirement_ids", []) for c in conflicts))
    summary = {
        "workshops_by_area": {a: {"held": sum(1 for w in workshops if w.get("process_area") == a and w.get("status") != "planned"),
                                  "planned": sum(1 for w in workshops if w.get("process_area") == a)} for a in {w.get("process_area") for w in workshops}},
        "requirements": {"captured": len(reqs), "validated": sum(1 for _, v in reqs if v), "open": sum(1 for _, v in reqs if not v)},
        "quality_trend": {"per_workshop": {s["workshop_id"]: s["total"] for s in scored}, "per_area": {a: round(sum(v) / len(v), 1) for a, v in by_area.items()}},
        "top_coverage_gaps": [{"area": a, "referencing_requirements": c} for a, c in sorted(referenced.items(), key=lambda x: -x[1])[:5]],
        "cross_team_flags": {"open": sum(1 for f in flags if f.status == ProposalStatus.PENDING),
                             "raised": sum(1 for f in flags if f.status == ProposalStatus.APPLIED),
                             "dismissed": sum(1 for f in flags if f.status == ProposalStatus.REJECTED)},
        "open_conflicts": len(conflicts),
        "duplicate_merges_pending": len(ctx.proposals("merge_proposal", ProposalStatus.PENDING)),
        "highest_urgency_pain_points": [{"id": e.get("id"), "as_is": e.get("as_is")} for e in urgent],
        "template_version": (sorted(ctx.register("template_version"), key=lambda d: d["seq"]) or [{"version": "v1.0"}])[-1]["version"],
        "handoff_readiness_pct": pct(done, len(reqs), 0.0),
        "next_workshops": [w["id"] for w in workshops if w.get("status") == "planned"][:5],
    }
    out.items.append(draft("weekly_summary", f"Weekly summary: {len(scored)} workshops scored", {"id": f"ws-{ctx.event.id}", **summary}))
    rb = rebaseline_check(ctx, scored)
    if rb:
        out.items.append(draft("rebaseline_decision", "Re-baseline recommended", {"id": f"rb-{ctx.event.id}", "tier": 2, **rb}))
    return out
