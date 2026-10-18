"""Build-phase tools: traceability chain, DoD gate, change impact, reuse search, cutover checks."""

from __future__ import annotations

from typing import Any

from ..domain.models import AgentItem
from .base import ToolContext, ToolOutput, det_tool, draft, filled, overlap, post_tool, pre_tool
from .scoring import drivers, effective_weights, load_rubric, rate, weighted_total

# Traceability chain: Requirement -> FS section -> TS component -> Code object -> Test case -> Cutover task
CHAIN_FIELDS = [("fs_ids", "FS section"), ("ts_ids", "TS component"), ("code_objects", "code object"), ("test_case_ids", "test case")]


def _cutover_tasks_for(ctx: ToolContext, object_id: str) -> list[dict[str, Any]]:
    return [t for t in ctx.register("cutover_task") if object_id in t.get("object_ids", []) and t.get("state") != "Obsolete"]


def dod_checks(ctx: ToolContext, obj: dict[str, Any]) -> list[dict[str, Any]]:
    th = load_rubric(ctx.settings.config_dir, "build_quality")["dod"]
    tasks = _cutover_tasks_for(ctx, obj["id"])
    no_task = obj.get("no_cutover_task_needed")
    task_gaps = [t["task_id"] for t in tasks if not (filled(t.get("owner")) and filled(t.get("duration_hours_likely")))]
    trace_gaps = [label for f, label in CHAIN_FIELDS if not obj.get(f)] + ([] if obj.get("requirement_ids") else ["requirement"])
    score = obj.get("rubric_score")

    def chk(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
        return {"check": name, "passed": bool(passed), "detail": detail}

    return [
        chk("FS approved", obj.get("fs_status") == "approved"),
        chk("TS approved", obj.get("ts_status") == "approved"),
        chk("code review Pass or approved Conditional", obj.get("code_review_verdict") in ("Pass", "Conditional-approved")),
        chk("ATC clean", obj.get("atc_clean") is True),
        chk(f"unit tests executed, coverage >= {th['min_test_coverage_pct']}%",
            obj.get("unit_tests_executed") is True and float(obj.get("coverage_pct", 0)) >= th["min_test_coverage_pct"],
            f"coverage {obj.get('coverage_pct', 0)}%"),
        chk(f"deliverable rubric score >= {th['min_rubric_score']}", score is not None and float(score) >= th["min_rubric_score"], f"score {score}"),
        chk("transport notes complete", obj.get("transport_notes_complete") is True),
        chk("traceability complete", not trace_gaps, "missing: " + ", ".join(trace_gaps) if trace_gaps else ""),
        chk("cutover tasks identified with owners and durations",
            (bool(tasks) or bool(no_task)) and not task_gaps,
            "no cutover task and not marked 'no task needed'" if not tasks and not no_task else f"incomplete: {task_gaps}"),
    ]


@det_tool("build_dod_gate")
def build_dod_gate(ctx: ToolContext) -> ToolOutput:
    wanted = ctx.event.payload.get("object_id")
    objs = [o for o in ctx.register("ricefw_object") if not wanted or o["id"] == wanted]
    out = ToolOutput()
    for o in objs:
        checks = dod_checks(ctx, o)
        blockers = [c["check"] for c in checks if not c["passed"]]
        out.items.append(draft("dod_verdict", f"DoD {o['id']}: {'ready for SIT' if not blockers else 'blocked'}", {
            "id": f"dod-{o['id']}-{ctx.event.id}", "object_id": o["id"], "ready_for_sit": not blockers,
            "checks": checks, "blockers": blockers}))
    return out


@det_tool("build_change_impact")
def build_change_impact(ctx: ToolContext) -> ToolOutput:
    rid = ctx.event.payload.get("requirement_id")
    if not rid:
        return ToolOutput()
    objs = [o for o in ctx.register("ricefw_object") if rid in o.get("requirement_ids", [])]
    impact = {
        "requirement_id": rid,
        "fs_sections": sorted({x for o in objs for x in o.get("fs_ids", [])}),
        "ts_components": sorted({x for o in objs for x in o.get("ts_ids", [])}),
        "code_objects": sorted({x for o in objs for x in o.get("code_objects", [])}),
        "test_cases": sorted({x for o in objs for x in o.get("test_case_ids", [])}),
        "cutover_tasks": sorted({t["task_id"] for o in objs for t in _cutover_tasks_for(ctx, o["id"])}),
        "re_review": sorted(o["id"] for o in objs),
        "re_test": sorted({x for o in objs for x in o.get("test_case_ids", [])}),
    }
    out = ToolOutput(reports=[{"kind": "change_impact", "id": ctx.event.id, "data": impact}])
    if any(o.get("deployed") for o in objs):
        out.events.append(("cutover.review.requested", {"reason": "change_impact", "requirement_id": rid}))
    return out


@pre_tool("reuse_search")
def reuse_search(ctx: ToolContext) -> ToolOutput:
    query = " ".join(str(ctx.event.payload.get(k, "")) for k in ("title", "text", "requirement_text"))[:2000]
    scored = []
    for o in ctx.register("past_ricefw"):
        s = overlap(query, f"{o.get('title', '')} {o.get('description', '')} {o.get('ricefw_type', '')} {o.get('process_area', '')}")
        if s > 0.05:
            scored.append((round(s, 2), {k: o.get(k) for k in ("id", "title", "ricefw_type", "process_area", "ref")}))
    return ToolOutput(facts={"reuse_candidates": [dict(score=s, **o) for s, o in sorted(scored, key=lambda x: -x[0])[:5]]})


@pre_tool("cutover_quality")
def cutover_quality(ctx: ToolContext) -> ToolOutput:
    tasks = [t for t in ctx.register("cutover_task")]
    covered = {o for t in tasks if t.get("state") != "Obsolete" for o in t.get("object_ids", [])}
    marked_none = {o["id"] for o in ctx.register("ricefw_object") if o.get("no_cutover_task_needed")}
    objects = [o["id"] for o in ctx.register("ricefw_object")]
    transports = ctx.register("transport")
    incomplete = [
        {"task_id": t["task_id"], "missing": [f for f in ("owner", "duration_hours_likely", "target_environments", "verification") if not filled(t.get(f))]}
        for t in tasks if t.get("state") != "Obsolete"
    ]
    return ToolOutput(facts={
        "existing_tasks": [{k: t.get(k) for k in ("task_id", "description", "state", "owner", "version", "object_ids")} for t in tasks][:300],
        "objects_without_cutover_task": sorted(set(objects) - covered - marked_none),
        "transports_without_task": sorted(str(t["id"]) for t in transports if not set(t.get("object_ids", [])) & covered),
        "tasks_with_missing_fields": [i for i in incomplete if i["missing"]],
        "rule": "Flag missing owner/duration/environment/verification; never guess them. Mark changed or removed tasks Changed/Obsolete.",
    })


@post_tool("apply_rubric")
def apply_rubric(ctx: ToolContext, items: list[AgentItem]) -> list[AgentItem]:
    rubric = load_rubric(ctx.settings.config_dir, "build_quality")
    weights = effective_weights(rubric, None)
    out = []
    for it in items:
        if it.kind == "guideline_change":
            it.payload["tier"] = 3  # rule-library changes need two distinct approvers
        if it.kind != "quality_score":
            out.append(it)
            continue
        dims = {k: float(v) for k, v in (it.payload.get("dimension_scores") or {}).items()}
        try:
            total = weighted_total(dims, weights)
        except ValueError as e:
            it.payload["error"] = str(e)
            out.append(it)
            continue
        it.payload.update(total=total, rating=rate(total, rubric["thresholds"], []), drivers=drivers(dims, weights),
                          weights=weights, rubric_version=rubric["version"])
        out.append(it)
    return out
