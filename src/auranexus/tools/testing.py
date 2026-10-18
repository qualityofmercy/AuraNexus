"""Test-phase tools: tracker generation, dependency waves, coverage/readiness, handoffs, duration variance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..domain.models import AgentItem, Notification, utcnow
from . import graph
from .base import ToolContext, ToolOutput, det_tool, draft, pct, post_tool, pre_tool

DONE = {"Passed"}
CATEGORIES_STRONG = {"negative", "authorization", "error", "boundary", "interface"}
DEFAULT_EXIT = {"pct_executed": 95.0, "pct_passed": 90.0, "max_open_sev1": 0, "max_open_sev2": 0}
NUDGE_AFTER = timedelta(minutes=30)
ESCALATE_AFTER = timedelta(hours=2)


def _when(v: Any) -> str:
    d = _ts(v)
    return d.strftime("%d %b %H:%M UTC") if d else "n/a"


def _ts(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


@det_tool("test_starter")
def test_starter(ctx: ToolContext) -> ToolOutput:
    scripts = ctx.event.payload.get("scripts", [])
    seen, rows, issues = set(), [], []
    for s in scripts:
        tid = str(s.get("test_id", "")).strip()
        if not tid or tid in seen:
            issues.append(f"missing or duplicate test_id: {tid or '<blank>'}")
            continue
        seen.add(tid)
        preds = list(s.get("predecessor_ids", []))
        row = {
            "test_id": tid, "scenario": s.get("scenario"), "process_area": s.get("process_area"),
            "scope_item": s.get("scope_item"), "requirement_ids": s.get("requirement_ids", []),
            "step_owner": s.get("step_owner"), "role": s.get("role"), "system_client": s.get("system_client"),
            "test_data_ref": s.get("test_data_ref"), "planned_start": s.get("planned_start"), "planned_end": s.get("planned_end"),
            "category": s.get("category", "positive"), "predecessor_ids": preds,
            "status": "Ready" if not preds else "Not Started",
        }
        if not row["step_owner"]:
            issues.append(f"{tid}: no step owner assigned")
        rows.append(row)
    ids = {r["test_id"] for r in rows}
    for r in rows:
        for p in r["predecessor_ids"]:
            if p not in ids:
                issues.append(f"{r['test_id']}: unknown predecessor {p}")
    return ToolOutput(items=[draft("test_tracker", f"Test tracker: {len(rows)} scripts", {
        "id": f"trk-{ctx.event.id}", "rows": rows, "issues": issues,
        "workbook": "GET /v1/projects/{id}/exports/test-tracker.xlsx once approved"})])


@post_tool("test_waves")
def test_waves(ctx: ToolContext, items: list[AgentItem]) -> list[AgentItem]:
    cases = {c["test_id"]: c for c in ctx.register("test_case")}
    edges = [(p, c["test_id"]) for c in cases.values() for p in c.get("predecessor_ids", [])]
    for it in items:
        if it.kind == "test_dependency" and it.payload.get("predecessor_id") and it.payload.get("test_id"):
            edges.append((it.payload["predecessor_id"], it.payload["test_id"]))
    res = graph.analyse(list(cases), edges)
    inferred = [it.title for it in items if it.kind == "test_dependency" and (it.inferred or not it.payload.get("documented"))]
    seq = draft("test_sequence", f"Execution plan: {len(res.waves)} waves", {
        "id": f"seq-{ctx.event.id}", **res.as_dict(),
        "note": "Scripts without dependencies run first (wave 1). Inferred dependencies are flagged for validation.",
        "inferred_dependencies": inferred})
    return [*items, seq]


def _cases(ctx: ToolContext) -> list[dict[str, Any]]:
    return ctx.register("test_case")


@det_tool("test_coverage")
def test_coverage(ctx: ToolContext) -> ToolOutput:
    phase = ctx.event.payload.get("phase", "mid")
    reqs = [r for r in ctx.register("requirement_entry") + ctx.register("requirement") if not r.get("duplicate_of")]
    cases = _cases(ctx)
    by_req: dict[str, list[dict]] = {}
    for c in cases:
        for rid in c.get("requirement_ids", []):
            by_req.setdefault(rid, []).append(c)
    cov, gaps = {}, []
    for r in reqs:
        cs = by_req.get(r["id"], [])
        cats = {c.get("category", "positive") for c in cs}
        level = "None" if not cs else "Full" if "positive" in cats and cats & CATEGORIES_STRONG else "Partial"
        cov[r["id"]] = level
        if level != "Full":
            gaps.append({"requirement_id": r["id"], "coverage": level,
                         "missing": [] if not cs else sorted({"negative path", "authorization check", "boundary values"} - {f"{c} path" if c == "negative" else c for c in cats})})
    per_scenario: dict[str, dict[str, Any]] = {}
    for c in cases:
        sc = per_scenario.setdefault(c.get("scenario") or "unassigned", {"total": 0, "passed": 0, "failed": 0, "blocked": 0, "executed": 0})
        sc["total"] += 1
        sc["passed"] += c.get("status") == "Passed"
        sc["failed"] += c.get("status") == "Failed"
        sc["blocked"] += c.get("status") == "Blocked"
        sc["executed"] += c.get("status") in ("Passed", "Failed")
    now = utcnow()
    due = [c for c in cases if (_ts(c.get("planned_end")) or now + timedelta(days=9999)) <= now]
    planned_pct = pct(len(due), len(cases), 0.0)
    executed = sum(1 for c in cases if c.get("status") in ("Passed", "Failed"))
    passed = sum(1 for c in cases if c.get("status") == "Passed")
    defects = [d for d in ctx.register("defect") if d.get("status") not in ("closed", "rejected")]
    aging = [{"id": d["id"], "severity": d.get("severity"), "age_days": (now - (_ts(d.get("opened")) or now)).days} for d in defects]
    data: dict[str, Any] = {
        "id": f"asm-{phase}-{ctx.event.id}", "phase": phase,
        "requirement_coverage": {"full": sum(v == "Full" for v in cov.values()), "partial": sum(v == "Partial" for v in cov.values()),
                                 "none": sum(v == "None" for v in cov.values())},
        "gaps": gaps, "per_scenario": per_scenario,
        "scenarios_at_risk": sorted(k for k, v in per_scenario.items() if v["failed"] or v["blocked"]),
        "executed_pct": pct(executed, len(cases), 0.0), "planned_to_date_pct": planned_pct,
        "pass_rate_pct": pct(passed, executed, 0.0),
        "blocked_scripts": sorted(c["test_id"] for c in cases if c.get("status") == "Blocked"),
        "open_defects": len(defects), "defect_aging": sorted(aging, key=lambda a: -a["age_days"])[:15],
    }
    if phase == "end":
        crit = {**DEFAULT_EXIT, **ctx.project.settings.get("exit_criteria", {})}
        sev = lambda n: sum(1 for d in defects if str(d.get("severity")) in (str(n), f"Severity {n}"))  # noqa: E731
        checks = {
            "executed": data["executed_pct"] >= crit["pct_executed"],
            "passed": data["pass_rate_pct"] >= crit["pct_passed"],
            "open_sev1": sev(1) <= crit["max_open_sev1"],
            "open_sev2": sev(2) <= crit["max_open_sev2"],
        }
        data.update(exit_criteria=crit, exit_checks=checks, go_no_go_input="go" if all(checks.values()) else "no-go",
                    residual_risk_by_scenario=data["scenarios_at_risk"])
    return ToolOutput(items=[draft("phase_assessment", f"{phase.title()}-phase assessment", data)])


@det_tool("test_handoff")
def test_handoff(ctx: ToolContext) -> ToolOutput:
    out = ToolOutput()
    cases = {c["test_id"]: c for c in _cases(ctx)}
    edges = [(p, c["test_id"]) for c in cases.values() for p in c.get("predecessor_ids", [])]
    now = utcnow()
    if ctx.event.type == "schedule.hourly":
        for c in cases.values():
            start = _ts(c.get("planned_start"))
            if c.get("status") != "Ready" or not start or now - start < NUDGE_AFTER:
                continue
            level = 2 if now - start >= ESCALATE_AFTER else 1
            nid = f"{c['test_id']}:{level}"
            if any(r["id"] == nid for r in ctx.reports("nudge")):
                continue
            out.reports.append({"kind": "nudge", "id": nid, "data": {"test_id": c["test_id"], "level": level}})
            out.notifications.append(Notification(tenant_id=ctx.tenant, project_id=ctx.pid, recipient=c.get("step_owner") or "test_lead",
                                                  subject=f"Reminder: {c['test_id']} is ready and not started", severity="warning",
                                                  body=f"{c['test_id']} ({c.get('scenario')}) was planned to start {_when(c.get('planned_start'))}. Please start or report a blocker.",
                                                  created_by="test.handoff_orchestrator"))
            if level == 2:
                out.items.append(draft("test_escalation", f"Escalate delayed start of {c['test_id']}", {
                    "id": f"esc-{nid}", "test_id": c["test_id"], "owner": c.get("step_owner"), "delay_minutes": int((now - start).total_seconds() // 60)}))
        return out

    tid, status = ctx.event.payload.get("test_id"), ctx.event.payload.get("status")
    case = cases.get(str(tid))
    if not case:
        return out
    produced = ctx.event.payload.get("produced", {})
    state = {k: c.get("status") for k, c in cases.items()}
    state[str(tid)] = status  # the event is authoritative, regardless of write ordering
    if status in DONE:
        for succ in sorted(n for n, c in cases.items() if tid in c.get("predecessor_ids", [])):
            sc = cases[succ]
            if all(state.get(p) in DONE for p in sc.get("predecessor_ids", [])):
                missing = [k for k in sc.get("required_inputs", []) if k not in produced and not cases[tid].get("produced", {}).get(k)]
                out.derived_writes.append(("test_case", succ, {**sc, "status": "Ready"}))
                note = f" Missing expected output: {', '.join(missing)}." if missing else ""
                data = ", ".join(f"{k} {v}" for k, v in produced.items())
                out.notifications.append(Notification(
                    tenant_id=ctx.tenant, project_id=ctx.pid, recipient=sc.get("step_owner") or "test_lead",
                    subject=f"Ready for you: {succ} ({sc.get('scenario', '')})",
                    body=f"Predecessor {tid} passed by {ctx.event.payload.get('actor', 'tester')}. {data + ' ready for your use.' if data else ''} "
                         f"Planned start: {_when(sc.get('planned_start'))}. Please confirm when you start.{note}".strip(),
                    created_by="test.handoff_orchestrator"))
    elif status in ("Failed", "Blocked"):
        blocked = sorted(graph.downstream(str(tid), edges))
        for b in blocked:
            out.notifications.append(Notification(
                tenant_id=ctx.tenant, project_id=ctx.pid, recipient=cases[b].get("step_owner") or "test_lead",
                subject=f"Heads-up: {b} is blocked by {tid} ({status})", severity="warning",
                body=f"{tid} is {status}. {b} cannot start until it passes or the sequence changes.", created_by="test.handoff_orchestrator"))
        if blocked:
            out.items.append(draft("test_resequence", f"Resequence around {tid} ({status})", {
                "id": f"rs-{tid}-{ctx.event.id}", "trigger_test": tid, "blocked_downstream": blocked,
                "proposal": "Run independent scripts first; hold dependants until the defect is fixed and the script is retested."}))
    return out


@pre_tool("duration_variance")
def duration_variance(ctx: ToolContext) -> ToolOutput:
    tasks = {t["task_id"]: t for t in ctx.register("cutover_task") if t.get("state") != "Obsolete"}
    rows = []
    for c in _cases(ctx):
        obs, tid = c.get("observed_duration_hours"), c.get("cutover_task_id")
        t = tasks.get(tid)
        if obs is None or not t or not t.get("duration_hours_likely"):
            continue
        plan = float(t["duration_hours_likely"])
        if plan and abs(float(obs) - plan) / plan > 0.25:
            rows.append({"task_id": tid, "planned_hours": plan, "observed_hours": float(obs), "source": c["test_id"],
                         "successors": [x["task_id"] for x in tasks.values() if tid in x.get("predecessors", [])]})
    return ToolOutput(facts={"duration_variances_over_25pct": rows,
                             "cutover_tasks": [{k: t.get(k) for k in ("task_id", "description", "owner", "duration_hours_likely", "predecessors")} for t in tasks.values()][:300]})
