"""Design-phase tools: readiness / scope-freeze gates, scope coverage assessment, build sequencing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..domain.models import AgentItem, ProposalStatus, utcnow
from . import graph
from .base import ToolContext, ToolOutput, det_tool, draft, filled, pct, post_tool

DECISION_MANDATORY = ["description", "rationale", "owner", "impacted_tracks"]
PRIORITY_WEIGHT = {"must": 4, "should": 3, "could": 2, "wont": 1}


def _reqs(ctx: ToolContext) -> list[dict[str, Any]]:
    return [r for r in ctx.register("requirement_entry") if r.get("type") in (None, "requirement", "pain_point")
            and not r.get("duplicate_of")]


def _applied(ctx: ToolContext, kind: str) -> list[Any]:
    return ctx.proposals(kind, ProposalStatus.APPLIED)


def _due(s: Any) -> bool:
    try:
        d = datetime.fromisoformat(str(s))
    except ValueError:
        return False
    return (d if d.tzinfo else d.replace(tzinfo=UTC)) < utcnow()


def readiness_checks(ctx: ToolContext) -> list[dict[str, Any]]:
    reqs, workshops = _reqs(ctx), ctx.register("workshop")
    decisions = ctx.register("decision")
    mapped = {rid for w in workshops for rid in w.get("requirement_ids", [])}
    deferred = {d.get("requirement_id") for d in ctx.register("scope_disposition") if d.get("disposition") == "deferred"}
    unmapped = sorted(str(r["id"]) for r in reqs if r["id"] not in mapped and r["id"] not in deferred)
    open_conflicts = [c["id"] for c in ctx.register("conflict") if c.get("status") == "open"]
    incomplete = [d["id"] for d in decisions if not all(filled(d.get(f)) for f in DECISION_MANDATORY)]
    signoffs: dict[str, list[dict]] = {}
    for s in ctx.register("signoff"):
        signoffs.setdefault(s["decision_id"], []).append(s)
    unsigned = sorted(d["id"] for d in decisions if not signoffs.get(d["id"]) or any(s.get("status") != "approved" for s in signoffs[d["id"]]))
    overdue = [a["id"] for a in ctx.register("assumption") if a.get("status") == "open" and a.get("critical") and _due(a.get("validation_due"))]
    status = {d["id"]: d.get("status") for d in decisions}
    inconsistent = sorted(d["id"] for d in decisions for dep in d.get("depends_on", []) if status.get(dep) == "reopened")
    def chk(name: str, blockers: list[str]) -> dict[str, Any]:
        return {"name": name, "passed": not blockers, "blockers": blockers}
    return [
        chk("all in-scope requirements mapped to a workshop or consciously deferred", unmapped),
        chk("no open conflicts", [str(c) for c in open_conflicts]),
        chk("every decision has its mandatory fields complete", [str(i) for i in incomplete]),
        chk("all required sign-offs received (including external)", [str(i) for i in unsigned]),
        chk("no overdue or unvalidated critical assumptions", [str(i) for i in overdue]),
        chk("no decision relies on a reopened one", [str(i) for i in inconsistent]),
    ]


def scope_freeze_checks(ctx: ToolContext) -> list[dict[str, Any]]:
    def chk(name: str, blockers: list[str]) -> dict[str, Any]:
        return {"name": name, "passed": not blockers, "blockers": blockers}
    est = _applied(ctx, "estimate")
    unack = [str(p.id) for p in est if str(p.payload.get("confidence_level", "")).lower() == "low" and not p.payload.get("acknowledged")]
    decisions = {d["id"]: d for d in ctx.register("decision")}
    signed = {s["decision_id"] for s in ctx.register("signoff") if s.get("status") == "approved"}
    shaky = sorted(
        str(o["id"]) for o in ctx.register("dev_object") if o.get("scope_status") == "in_scope"
        for d in o.get("decision_ids", []) if d not in signed or decisions.get(d, {}).get("status") == "reopened"
    )
    return [
        chk("scope coverage report reviewed and gaps dispositioned", [] if _applied(ctx, "scope_coverage_report") else ["no approved scope coverage report"]),
        chk("skills assessment reviewed", [] if _applied(ctx, "skills_matrix") else ["no approved skills matrix"]),
        chk("estimates reviewed, low-confidence items acknowledged", ([] if est else ["no approved estimates"]) + unack),
        chk("build sequence and dependencies reviewed", [] if _applied(ctx, "build_plan") else ["no approved build plan"]),
        chk("no object rests on an unsigned or reopened decision", shaky),
    ]


@det_tool("design_gates")
def design_gates(ctx: ToolContext) -> ToolOutput:
    et = ctx.event.type
    out = ToolOutput()
    reqs, decisions, signoffs = _reqs(ctx), ctx.register("decision"), ctx.register("signoff")
    mapped = {rid for w in ctx.register("workshop") for rid in w.get("requirement_ids", [])}
    pending_by_person: dict[str, int] = {}
    for s in signoffs:
        if s.get("status") in ("requested", "pending"):
            pending_by_person[s.get("stakeholder", "?")] = pending_by_person.get(s.get("stakeholder", "?"), 0) + 1
    dash = {
        "requirements_covered_pct": pct(sum(1 for r in reqs if r["id"] in mapped), len(reqs)),
        "decisions": len(decisions),
        "signoffs": {s: sum(1 for x in signoffs if x.get("status") == s) for s in ("requested", "pending", "approved", "rejected")},
        "stakeholder_fatigue": dict(sorted(pending_by_person.items(), key=lambda kv: -kv[1])[:10]),
        "open_assumptions": sum(1 for a in ctx.register("assumption") if a.get("status") == "open"),
        "open_conflicts": sum(1 for c in ctx.register("conflict") if c.get("status") == "open"),
    }
    out.reports.append({"kind": "dashboard", "id": ctx.event.id, "data": dash})
    gate = "design_readiness" if et == "gate.design_readiness.requested" else "scope_freeze" if et == "gate.scope_freeze.requested" else None
    if gate:
        checks = readiness_checks(ctx) if gate == "design_readiness" else scope_freeze_checks(ctx)
        go = all(c["passed"] for c in checks)
        out.items.append(draft("gate_decision", f"{gate.replace('_', ' ').title()} gate: {'GO' if go else 'NO-GO'}",
                               {"id": f"{gate}-{ctx.event.id}", "gate": gate, "recommendation": "go" if go else "no-go",
                                "checks": checks, "blocking_items": [b for c in checks for b in c["blockers"]]}))
    return out


@det_tool("scope_coverage")
def scope_coverage(ctx: ToolContext) -> ToolOutput:
    reqs, decisions = _reqs(ctx), ctx.register("decision")
    objects = ctx.register("dev_object")
    disp = {d.get("requirement_id"): d.get("disposition") for d in ctx.register("scope_disposition")}
    by_req = {r["id"]: [o for o in objects if r["id"] in o.get("requirement_ids", [])] for r in reqs}
    dependents: dict[str, int] = {}
    for dep in ctx.register("object_dependency"):
        dependents[dep["from"]] = dependents.get(dep["from"], 0) + 1

    def significance(item: dict[str, Any], objs: list[dict[str, Any]]) -> int:
        return (PRIORITY_WEIGHT.get(str(item.get("priority", "")).lower(), 2) * 2 + int(item.get("process_criticality", 1))
                + (3 if item.get("regulatory") else 0) + sum(dependents.get(o["id"], 0) for o in objs))

    gaps: list[dict[str, Any]] = []
    for r in reqs:
        if not by_req[r["id"]] and not disp.get(r["id"]):
            gaps.append({"type": "requirement_without_scope_item", "ref": r["id"], "detail": r.get("as_is") or r.get("title"),
                         "significance": significance(r, [])})
    obj_decisions = {d for o in objects for d in o.get("decision_ids", [])}
    for d in decisions:
        if d.get("implies_development") and d["id"] not in obj_decisions:
            gaps.append({"type": "decision_without_object", "ref": d["id"], "detail": d.get("description"), "significance": significance(d, [])})
    for o in objects:
        if o.get("scope_status") == "in_scope" and not o.get("requirement_ids") and not o.get("decision_ids"):
            gaps.append({"type": "scope_item_without_requirement", "ref": o["id"], "detail": o.get("name"), "significance": 1,
                         "note": "possible scope creep"})
    tag_key = "brownfield_tags" if ctx.project.project_type.value == "brownfield" else "greenfield_tags"
    for r in reqs:
        for tag in r.get(tag_key, []) or []:
            if not disp.get(f"{r['id']}:{tag}") and not by_req[r["id"]]:
                gaps.append({"type": f"{ctx.project.project_type.value}_item_without_disposition", "ref": f"{r['id']}:{tag}",
                             "detail": tag, "significance": significance(r, [])})
    signed = {s["decision_id"] for s in ctx.register("signoff") if s.get("status") == "approved"}
    unsigned = sorted(str(o["id"]) for o in objects if o.get("scope_status") == "in_scope"
                      and any(d not in signed for d in o.get("decision_ids", [])))
    gaps.sort(key=lambda g: -g["significance"])
    return ToolOutput(items=[draft("scope_coverage_report", f"Scope coverage: {len(gaps)} gaps",
                                   {"id": f"scp-{ctx.event.id}", "gaps": gaps, "objects_on_unsigned_decisions": unsigned,
                                    "requirements_checked": len(reqs), "objects_checked": len(objects)})])


@det_tool("build_sequencer")
def build_sequencer(ctx: ToolContext) -> ToolOutput:
    objects = {o["id"]: o for o in ctx.register("dev_object") if o.get("scope_status") == "in_scope"}
    all_objects = {o["id"]: o for o in ctx.register("dev_object")}
    deps = ctx.register("object_dependency")
    hours = {p.payload.get("object_id"): float(p.payload.get("likely", 1)) for p in _applied(ctx, "estimate")}
    edges = [(d["from"], d["to"]) for d in deps]
    res = graph.analyse(list(objects), edges, hours)
    signed = {s["decision_id"] for s in ctx.register("signoff") if s.get("status") == "approved"}
    issues: list[dict[str, Any]] = [{"type": "circular_dependency", "objects": c} for c in res.cycles]
    for node, missing in res.missing_prerequisites:
        why = "not in scope" if missing in all_objects else "unknown object"
        issues.append({"type": "prerequisite_unavailable", "object": node, "prerequisite": missing, "reason": why})
    for o in objects.values():
        if any(d not in signed for d in o.get("decision_ids", [])):
            issues.append({"type": "object_on_unsigned_decision", "object": o["id"]})
    sinks = [n for n in objects if not any(a == n for a, _ in edges)]
    chains = []
    for s in sinks[:10]:
        preds = [a for a, b in edges if b == s]
        chains.append({"scenario": f"E2E ending at {objects[s].get('name', s)}", "objects": sorted(set(preds + [s]))})
    waves = []
    for i, w in enumerate(res.waves):
        waves.append({
            "wave": f"W{i + 1}", "objects": w,
            "entry_criteria": ["previous wave exit criteria met", "prerequisite objects unit tested"] if i else ["design signed off"],
            "exit_criteria": ["unit tests passed", "integration test set passed"],
            "integration_tests": [o for o in w if objects[o].get("type") in ("interface", "conversion", "enhancement")],
        })
    return ToolOutput(items=[draft("build_plan", f"Build plan: {len(waves)} waves", {
        "id": f"bp-{ctx.event.id}", "waves": waves, "critical_path": res.critical_path,
        "critical_path_hours": res.critical_length, "issues": issues, "e2e_test_candidates": chains,
        "basis": "approved estimates (likely hours) and registered object dependencies"})])


@post_tool("design_mandatory")
def design_mandatory(ctx: ToolContext, items: list[AgentItem]) -> list[AgentItem]:
    """Blank mandatory fields never get invented: they land in a 'needs attention' list for the human."""
    for it in items:
        if it.kind == "decision":
            missing = [f for f in DECISION_MANDATORY if not filled(it.payload.get(f))]
            it.payload["needs_attention"] = missing
    return items
