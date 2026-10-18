"""Run-phase tools: execution monitoring, frozen-rubric scoring, refinement post-processing, AI value metrics."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from ..domain.models import AgentItem, CheckpointStatus, Notification, ProposalStatus
from . import graph
from .base import ToolContext, ToolOutput, det_tool, draft, filled, overlap, pct, post_tool, pre_tool
from .scoring import drivers, effective_weights, load_rubric, rate, rubric_hash, weighted_total


class RubricFrozenError(RuntimeError):
    pass


def _ts(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _hours(a: Any, b: Any) -> float | None:
    x, y = _ts(a), _ts(b)
    return (y - x).total_seconds() / 3600 if x and y else None


def rehearsal_of(ctx: ToolContext) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    rid = ctx.event.payload.get("rehearsal_id")
    rs = ctx.register("rehearsal")
    r = next((x for x in rs if x["id"] == rid), None) if rid else (sorted(rs, key=lambda x: str(x.get("window_start")))[-1] if rs else None)
    tasks = [t for t in ctx.register("rehearsal_task") if r and t.get("rehearsal_id") == r["id"]]
    return r, tasks


def classify_task(t: dict[str, Any]) -> tuple[str, float | None]:
    """smooth / watch / problem from variance against plan (hours); failure or restart is always a problem."""
    planned = _hours(t.get("planned_start"), t.get("planned_end"))
    actual = _hours(t.get("actual_start"), t.get("actual_end"))
    if t.get("status") in ("failed", "restarted"):
        return "problem", None
    if planned is None or actual is None:
        return "watch" if t.get("status") == "in_progress" else "smooth", None
    var = (actual - planned) / planned if planned else 0.0
    start_delay = _hours(t.get("planned_start"), t.get("actual_start")) or 0.0
    if var > 0.25 or start_delay > 0.5:
        return "problem", round(var * 100, 1)
    if var > 0.10 or start_delay > 0.25:
        return "watch", round(var * 100, 1)
    return "smooth", round(var * 100, 1)


@det_tool("run_execution_monitor")
def run_execution_monitor(ctx: ToolContext) -> ToolOutput:
    r, tasks = rehearsal_of(ctx)
    if not r or not tasks:
        return ToolOutput(facts={"note": "no rehearsal or tasks registered"})
    if ctx.event.type == "schedule.hourly" and r.get("status") != "in_progress":
        return ToolOutput(facts={"note": "no rehearsal in progress"})
    classes, flags = {}, []
    for t in tasks:
        classes[t["task_id"]] = classify_task(t)
        miss = [f for f in ("owner", "planned_start", "planned_end") if not filled(t.get(f))]
        if t.get("status") in ("completed", "failed") and not (t.get("actual_start") and t.get("actual_end")):
            miss.append("actuals")
        if miss:
            flags.append({"task_id": t["task_id"], "missing": miss})
    ids = [t["task_id"] for t in tasks]
    edges = [(p, t["task_id"]) for t in tasks for p in t.get("predecessors", [])]
    dur = {t["task_id"]: (_hours(t.get("actual_start"), t.get("actual_end")) or _hours(t.get("planned_start"), t.get("planned_end")) or 1.0) for t in tasks}
    cp = graph.analyse(ids, edges, dur)
    plan_dur = {t["task_id"]: _hours(t.get("planned_start"), t.get("planned_end")) or 1.0 for t in tasks}
    plan_cp = graph.analyse(ids, edges, plan_dur)
    projected_overrun = round(cp.critical_length - plan_cp.critical_length, 2)
    window_h = _hours(r.get("window_start"), r.get("window_end"))
    window_risk = bool(window_h and cp.critical_length > window_h)
    data = {
        "rehearsal_id": r["id"],
        "tasks": {k: {"classification": c, "variance_pct": v} for k, (c, v) in classes.items()},
        "counts": {c: sum(1 for x, _ in classes.values() if x == c) for c in ("smooth", "watch", "problem")},
        "critical_path": cp.critical_path, "critical_path_hours": round(cp.critical_length, 2),
        "planned_critical_path_hours": round(plan_cp.critical_length, 2), "projected_overrun_hours": projected_overrun,
        "window_hours": window_h, "window_at_risk": window_risk, "blocked": sorted(t["task_id"] for t in tasks if t.get("status") == "blocked"),
        "data_gaps": flags, "cycles": cp.cycles,
        "note": "Read-only view. Missing data is reported, not guessed.",
    }
    out = ToolOutput(reports=[{"kind": "execution_status", "id": f"{r['id']}-{ctx.event.id}", "data": data}])
    crit_problem = [t for t, (c, _) in classes.items() if c == "problem" and t in cp.critical_path]
    if window_risk or crit_problem:  # immediate alerts only for critical path / window risk (alert-fatigue guard)
        out.notifications.append(Notification(
            tenant_id=ctx.tenant, project_id=ctx.pid, recipient="cutover_lead", severity="critical",
            subject=f"{r['id']}: " + ("projected window overrun" if window_risk else "critical-path task in trouble"),
            body=f"Projected critical path {data['critical_path_hours']}h vs plan {data['planned_critical_path_hours']}h "
                 f"(window {window_h}h). Problem tasks on the critical path: {', '.join(crit_problem) or 'none'}.",
            created_by="run.execution_monitor"))
    return out


# --------------------------------------------------------------------------------- scoring

def _dimension_scores(ctx: ToolContext, r: dict[str, Any], tasks: list[dict[str, Any]], tol: float) -> tuple[dict[str, float], list[str], list[str]]:
    missing: list[str] = []
    n = len(tasks) or 1
    # schedule: window overrun is punished hard (x400), mean task variance moderately
    planned = _hours(r.get("window_start"), r.get("window_end"))
    ends = [t["actual_end"] for t in tasks if t.get("actual_end")]
    starts = [t["actual_start"] for t in tasks if t.get("actual_start")]
    used = _hours(min(starts), max(ends)) if starts and ends else None
    var = [classify_task(t)[1] for t in tasks]
    var = [v for v in var if v is not None]
    if planned and used is not None:
        overrun = max(0.0, (used - planned) / planned)
        schedule = max(0.0, 100 - min(100.0, overrun * 400) - min(30.0, max(0.0, sum(var) / len(var)) * 0.5 if var else 0.0))
    else:
        schedule = 0.0
        missing.append("window or actual timestamps (schedule adherence)")
    clean = sum(1 for t in tasks if t.get("status") == "completed" and not t.get("manual_intervention") and not t.get("restarted"))
    execution = pct(clean, n, 0.0)
    recon = [x for x in ctx.register("reconciliation") if x.get("rehearsal_id") == r["id"]]
    if recon:
        rej = sum(float(x.get("rejection_pct", 0)) for x in recon) / len(recon)
        data = max(0.0, sum(float(x["reconciliation_pct"]) for x in recon) / len(recon) - rej * 2)
    else:
        data = 0.0
        missing.append("reconciliation reports (data integrity)")
    defects = [d for d in ctx.register("defect") if d.get("rehearsal_id") == r["id"]]
    w = {"critical": 25, "high": 10, "medium": 4, "low": 1}
    pen = sum(w.get(str(d.get("severity")).lower(), 4) * (1 if d.get("status") not in ("closed", "resolved") else 0.5) for d in defects)
    pen += 10 * sum(1 for d in defects if d.get("repeat"))
    issue = max(0.0, 100 - pen)
    late = 0
    by_id = {t["task_id"]: t for t in tasks}
    for t in tasks:
        ends_p = [_ts(by_id[p].get("actual_end")) for p in t.get("predecessors", []) if p in by_id and by_id[p].get("actual_end")]
        st = _ts(t.get("actual_start"))
        if ends_p and st and (st - max(ends_p)).total_seconds() > 15 * 60:
            late += 1
    handoffs = pct(n - late, n)
    rollback = (50 if r.get("rollback_tested") else 0) + (25 if any(t.get("rollback_point") for t in tasks) else 0) \
        + 25 * pct(sum(1 for t in tasks if filled(t.get("backup_owner"))), n, 0.0) / 100
    if "rollback_tested" not in r:
        missing.append("rollback test result")
    scores = {"schedule_adherence": round(schedule, 1), "execution_quality": execution, "data_integrity": round(data, 1),
              "issue_management": round(issue, 1), "readiness_handoffs": handoffs, "rollback_readiness": round(rollback, 1)}
    forced = []
    if any(not x.get("resolved") and float(x.get("breach_pct", 0)) > tol for x in recon):
        forced.append("unresolved data-integrity breach above agreed tolerance")
    if r.get("rollback_tested") is not True:
        forced.append("rollback untested or failed")
    if any(str(d.get("severity")).lower() == "critical" and d.get("status") not in ("closed", "resolved") for d in defects):
        forced.append("critical-severity defect still open")
    return scores, missing, forced


@det_tool("run_scoring")
def run_scoring(ctx: ToolContext) -> ToolOutput:
    r, tasks = rehearsal_of(ctx)
    if not r:
        return ToolOutput()
    rubric = load_rubric(ctx.settings.config_dir, "cutover_scoring")
    profile = ctx.project.project_type.value
    weights = effective_weights(rubric, profile)
    digest = rubric_hash({**rubric, "weights": weights})
    freeze = ctx.register("rubric_freeze")
    if freeze and freeze[-1]["hash"] != digest:
        raise RubricFrozenError(
            f"scoring rubric changed since freeze ({freeze[-1]['hash']} -> {digest}); a PM must approve a new rubric version")
    if not freeze:
        ctx.repo.register_put(ctx.tenant, ctx.pid, "rubric_freeze", f"rf-{digest}",
                              {"hash": digest, "version": rubric["version"], "weights": weights, "frozen_at": ctx.event.created_at.isoformat(), "status": "frozen"})
    scores, missing, forced = _dimension_scores(ctx, r, tasks, rubric["overrides"]["data_integrity_breach_pct"])
    total = weighted_total(scores, weights)
    rating = rate(total, rubric["thresholds"], forced)
    prev = [s for s in ctx.register("scorecard") if s.get("rehearsal_id") != r["id"]]
    prev_total = sorted(prev, key=lambda s: str(s.get("decided_at")))[-1]["total"] if prev else None
    return ToolOutput(
        items=[draft("scorecard", f"{r.get('name', r['id'])}: {total} ({rating})", {
            "id": f"sc-{r['id']}", "rehearsal_id": r["id"], "dimension_scores": scores, "weights": weights, "total": total,
            "rating": rating, "overrides_applied": forced, "drivers": drivers(scores, weights),
            "trend_vs_previous": None if prev_total is None else round(total - prev_total, 1),
            "missing_data": missing, "confidence": "Low" if len(missing) > 1 else "Medium" if missing else "High",
            "rubric_version": rubric["version"], "rubric_hash": digest, "profile": profile,
            "explanation": "Scores are computed deterministically from plan actuals, reconciliation, defects and checkpoints."})],
        events=[("rehearsal.scored", {"rehearsal_id": r["id"], "rating": rating, "total": total})],
    )


# ------------------------------------------------------------------- refinement / retrospective

TIER3 = re.compile(r"rollback|point of no return|data migration|reconciliation|sign-?off|tolerance|business", re.I)
TIER2 = re.compile(r"sequenc|dependen|owner|hand-?off|parallel|checkpoint|predecessor", re.I)


@post_tool("refinement_post")
def refinement_post(ctx: ToolContext, items: list[AgentItem]) -> list[AgentItem]:
    code = str(ctx.event.payload.get("rehearsal_code") or ctx.event.payload.get("rehearsal_id", "DR")).upper()
    prior = ctx.repo.list_proposals(ctx.tenant, ctx.pid, kind="refinement_proposal")
    seq = max(len(prior), int(ctx.project.settings.get("refinement_seq_start", 1)) - 1)
    out = []
    for it in items:
        if it.kind != "refinement_proposal":
            out.append(it)
            continue
        seq += 1
        text = " ".join(str(it.payload.get(k, "")) for k in ("proposed_change", "observation", "affected"))
        tier = 3 if TIER3.search(text) else 2 if TIER2.search(text) else 1
        hit = max(((overlap(text, " ".join(str(p.payload.get(k, "")) for k in ("proposed_change", "observation"))), p) for p in prior), key=lambda x: x[0], default=(0.0, None))
        repeat = hit[0] >= 0.5 and hit[1] is not None
        it.payload.update(proposal_id=f"CP-{code}-{seq:03d}", tier=tier, repeat_issue=repeat,
                          repeat_of=hit[1].payload.get("proposal_id") if repeat else None,
                          priority="high" if repeat else it.payload.get("priority", "normal"))
        out.append(it)
    return out


@pre_tool("ai_value_metrics")
def ai_value_metrics(ctx: ToolContext) -> ToolOutput:
    cps = ctx.repo.list_checkpoints(ctx.tenant, ctx.pid)
    decided = [c for c in cps if c.status == CheckpointStatus.DECIDED and c.decision]
    outcomes = {o: sum(1 for c in decided if c.decision.outcome.value == o) for o in ("approve", "modify", "reject", "defer")}
    refs = ctx.repo.list_proposals(ctx.tenant, ctx.pid, kind="refinement_proposal")
    rdec = [p for p in refs if p.status in (ProposalStatus.APPLIED, ProposalStatus.REJECTED)]
    cards = sorted(ctx.register("scorecard"), key=lambda s: str(s.get("rehearsal_id")))
    findings = ctx.reports("observation")  # observation-logger output (informational)
    first = [f for f in findings if f.get("rehearsal_id") == (cards[0]["rehearsal_id"] if cards else None) and f.get("classification") == "problem"]
    last_id = cards[-1]["rehearsal_id"] if cards else None
    last = [f for f in findings if f.get("rehearsal_id") == last_id and f.get("classification") == "problem"]
    eliminated = [f["id"] for f in first if not any(overlap(str(f.get("what_happened")), str(g.get("what_happened"))) > 0.5 for g in last)]
    risks = ctx.register("risk_log")
    return ToolOutput(facts={
        "hitl_outcomes": outcomes, "proposal_acceptance_rate_pct": pct(sum(1 for p in rdec if p.status == ProposalStatus.APPLIED), len(rdec), 0.0) if rdec else None,
        "score_trend": [{"rehearsal": c["rehearsal_id"], "total": c["total"], "rating": c["rating"]} for c in cards],
        "repeat_issues_eliminated": {"dry_run_1_problems": len(first), "eliminated": len(eliminated)},
        "risks": {"flagged_by_agents": sum(1 for x in risks if x.get("source") == "agent"),
                  "materialized": sum(1 for x in risks if x.get("source") == "agent" and x.get("outcome") == "materialized")},
        "windows": [{"rehearsal": r["id"], "planned_hours": _hours(r.get("window_start"), r.get("window_end")), "actual_hours": r.get("actual_window_hours")} for r in ctx.register("rehearsal")],
        "observations": [{k: f.get(k) for k in ("id", "rehearsal_id", "task_id", "classification", "what_happened", "category")} for f in findings][:200],
        "baseline_note": "Effort-saved claims need baseline hours from comparable past projects; absent baselines must be stated, not estimated.",
    })


def current_rubric_digest(config_dir: Any, profile: str) -> tuple[str, dict[str, Any]]:
    rubric = load_rubric(config_dir, "cutover_scoring")
    weights = effective_weights(rubric, profile)
    return rubric_hash({**rubric, "weights": weights}), {"version": rubric["version"], "weights": weights}
