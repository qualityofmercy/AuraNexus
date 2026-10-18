"""Deterministic tools: scoring, gates, handoffs, sequencing."""

from datetime import timedelta

import pytest

from auranexus.domain.models import Event, utcnow
from auranexus.tools.base import ToolContext
from auranexus.tools.build import build_dod_gate
from auranexus.tools.design import build_sequencer, design_gates, scope_coverage
from auranexus.tools.run import RubricFrozenError, run_execution_monitor, run_scoring
from auranexus.tools.testing import test_coverage as coverage_tool
from auranexus.tools.testing import test_handoff as handoff_tool

from .conftest import PID, TENANT, Harness


def ctx(h: Harness, etype="x", payload=None) -> ToolContext:
    return ToolContext(h.c.repo, h.c.repo.get_project(TENANT, PID), Event(tenant_id=TENANT, project_id=PID, type=etype, payload=payload or {}), h.settings)


def reg(h, kind, id, **data):
    h.c.repo.register_put(TENANT, PID, kind, id, data)


def iso(minutes: float) -> str:
    return (utcnow() + timedelta(minutes=minutes)).isoformat()


# --------------------------------------------------------------------------------- run phase

def seed_rehearsal(h, *, rollback_tested=True, crit_defect=False, overrun=False):
    base = -600
    reg(h, "rehearsal", "DR1", name="Dry Run 1", status="complete", window_start=iso(base), window_end=iso(base + 240), rollback_tested=rollback_tested)
    spec = [("T1", 0, 60, []), ("T2", 60, 120, ["T1"]), ("T3", 120, 200 if not overrun else 400, ["T2"])]
    for tid, s, e, pre in spec:
        reg(h, "rehearsal_task", f"DR1:{tid}", rehearsal_id="DR1", task_id=tid, planned_start=iso(base + s), planned_end=iso(base + e),
            actual_start=iso(base + s), actual_end=iso(base + e), status="completed", predecessors=pre, owner="o", backup_owner="b",
            rollback_point=tid == "T2")
    reg(h, "reconciliation", "r1", rehearsal_id="DR1", reconciliation_pct=100, rejection_pct=0, resolved=True, breach_pct=0)
    if crit_defect:
        reg(h, "defect", "d1", rehearsal_id="DR1", severity="critical", status="open")


def test_scoring_green_and_explained(h):
    seed_rehearsal(h)
    out = run_scoring(ctx(h, "rehearsal.completed", {"rehearsal_id": "DR1"}))
    p = out.items[0].payload
    assert p["rating"] == "Green" and p["total"] >= 85 and p["overrides_applied"] == []
    assert p["drivers"]["positive"] and p["profile"] == "greenfield"
    assert abs(sum(p["weights"].values()) - 100) < 1e-9


def test_scoring_override_caps_at_red(h):
    seed_rehearsal(h, crit_defect=True)
    p = run_scoring(ctx(h, "rehearsal.completed", {"rehearsal_id": "DR1"})).items[0].payload
    assert p["rating"] == "Red" and "critical-severity defect still open" in p["overrides_applied"]


def test_scoring_flags_missing_data_and_untested_rollback(h):
    seed_rehearsal(h, rollback_tested=False)
    p = run_scoring(ctx(h, "rehearsal.completed", {"rehearsal_id": "DR1"})).items[0].payload
    assert p["rating"] == "Red" and "rollback untested or failed" in p["overrides_applied"]


def test_rubric_cannot_change_after_freeze(h):
    seed_rehearsal(h)
    run_scoring(ctx(h, "rehearsal.completed", {"rehearsal_id": "DR1"}))
    h.c.repo.register_put(TENANT, PID, "rubric_freeze", "rf-bad", {"hash": "tampered", "seq": 9})
    # newest freeze wins in the tool: simulate a changed rubric by tampering with the stored hash
    frozen = h.c.repo.register_list(TENANT, PID, "rubric_freeze")
    for f in frozen:
        h.c.repo.register_put(TENANT, PID, "rubric_freeze", f["id"], {**f, "hash": "tampered"})
    with pytest.raises(RubricFrozenError):
        run_scoring(ctx(h, "rehearsal.completed", {"rehearsal_id": "DR1"}))


def test_brownfield_weights_differ():
    from auranexus.config import Settings
    from auranexus.tools.scoring import effective_weights, load_rubric

    r = load_rubric(Settings().config_dir, "cutover_scoring")
    assert effective_weights(r, "brownfield")["schedule_adherence"] == 30
    assert effective_weights(r, "greenfield")["data_integrity"] == 25


def test_execution_monitor_alerts_on_critical_path_overrun(h):
    base = -120
    reg(h, "rehearsal", "DR2", status="in_progress", window_start=iso(base), window_end=iso(base + 180))
    reg(h, "rehearsal_task", "DR2:A", rehearsal_id="DR2", task_id="A", planned_start=iso(base), planned_end=iso(base + 60), actual_start=iso(base),
        actual_end=iso(base + 150), status="completed", predecessors=[], owner="o")
    reg(h, "rehearsal_task", "DR2:B", rehearsal_id="DR2", task_id="B", planned_start=iso(base + 60), planned_end=iso(base + 120), status="not_started",
        predecessors=["A"], owner="o")
    out = run_execution_monitor(ctx(h, "rehearsal.actuals.updated", {"rehearsal_id": "DR2"}))
    data = out.reports[0]["data"]
    assert data["tasks"]["A"]["classification"] == "problem" and data["projected_overrun_hours"] > 0
    assert out.notifications and out.notifications[0].severity == "critical"


# --------------------------------------------------------------------------------- test phase

def seed_tests(h):
    for tid, pre in (("A", []), ("B", ["A"]), ("C", ["B"]), ("D", [])):
        reg(h, "test_case", tid, test_id=tid, scenario="O2C", step_owner=f"owner-{tid}", status="Ready" if not pre else "Not Started",
            predecessor_ids=pre, planned_start=iso(-5), requirement_ids=["R1"] if tid == "A" else [], category="positive")


def test_handoff_marks_successor_ready_and_notifies(h):
    seed_tests(h)
    out = handoff_tool(ctx(h, "test.status.updated", {"test_id": "A", "status": "Passed", "actor": "A. Sharma", "produced": {"Sales Order": "4500012345"}}))
    assert out.derived_writes[0][1] == "B" and out.derived_writes[0][2]["status"] == "Ready"
    n = out.notifications[0]
    assert n.recipient == "owner-B" and "4500012345" in n.body and "Ready for you: B" in n.subject


def test_failure_blocks_downstream_and_drafts_resequence(h):
    seed_tests(h)
    out = handoff_tool(ctx(h, "test.status.updated", {"test_id": "A", "status": "Failed"}))
    assert {n.recipient for n in out.notifications} == {"owner-B", "owner-C"}
    assert out.items[0].kind == "test_resequence" and out.items[0].payload["blocked_downstream"] == ["B", "C"]


def test_coverage_levels_and_end_phase_exit_criteria(h):
    seed_tests(h)
    reg(h, "requirement_entry", "R1", type="requirement")
    reg(h, "requirement_entry", "R2", type="requirement")
    p = coverage_tool(ctx(h, "test.assess.requested", {"phase": "end"})).items[0].payload
    assert p["requirement_coverage"] == {"full": 0, "partial": 1, "none": 1}
    assert p["go_no_go_input"] == "no-go" and p["exit_checks"]["executed"] is False


# --------------------------------------------------------------------------------- design & build

def test_design_readiness_gate_lists_blockers(h):
    reg(h, "requirement_entry", "R1", type="requirement")
    reg(h, "decision", "D1", description="x", rationale="", owner="o", impacted_tracks=["O2C"])
    reg(h, "conflict", "C1", status="open")
    p = design_gates(ctx(h, "gate.design_readiness.requested")).items[0].payload
    assert p["recommendation"] == "no-go"
    failed = {c["name"] for c in p["checks"] if not c["passed"]}
    assert len(failed) >= 4 and "R1" in p["blocking_items"] and "C1" in p["blocking_items"] and "D1" in p["blocking_items"]


def test_scope_coverage_ranks_must_above_could(h):
    reg(h, "requirement_entry", "R1", type="requirement", priority="Must", process_criticality=3, regulatory=True)
    reg(h, "requirement_entry", "R2", type="requirement", priority="Could", process_criticality=1)
    reg(h, "dev_object", "O9", name="Orphan", scope_status="in_scope", requirement_ids=[], decision_ids=[])
    gaps = scope_coverage(ctx(h, "scope.finalized")).items[0].payload["gaps"]
    assert [g["ref"] for g in gaps[:2]] == ["R1", "R2"]
    assert any(g["type"] == "scope_item_without_requirement" for g in gaps)


def test_build_sequencer_orders_prerequisites_and_flags_cycles(h):
    for oid in ("cfg", "enh", "itf", "x", "y"):
        reg(h, "dev_object", oid, name=oid, scope_status="in_scope", type="interface" if oid == "itf" else "config", decision_ids=[])
    for a, b in (("cfg", "enh"), ("enh", "itf"), ("x", "y"), ("y", "x")):
        reg(h, "object_dependency", f"{a}-{b}", **{"from": a, "to": b, "type": "technical"})
    p = build_sequencer(ctx(h, "estimates.reviewed")).items[0].payload
    assert [w["objects"] for w in p["waves"]] == [["cfg"], ["enh"], ["itf"]]
    assert p["waves"][2]["integration_tests"] == ["itf"]
    assert any(i["type"] == "circular_dependency" for i in p["issues"])


def test_dod_gate_requires_every_link(h):
    reg(h, "ricefw_object", "OBJ1", requirement_ids=["R1"], fs_ids=["FS1"], ts_ids=["TS1"], code_objects=["ZCL"], test_case_ids=["TC1"],
        fs_status="approved", ts_status="approved", code_review_verdict="Pass", atc_clean=True, unit_tests_executed=True,
        coverage_pct=85, rubric_score=82, transport_notes_complete=True)
    reg(h, "cutover_task", "CT1", task_id="CT1", object_ids=["OBJ1"], owner="basis", duration_hours_likely=1, state="New")
    assert build_dod_gate(ctx(h, "dod.requested")).items[0].payload["ready_for_sit"] is True
    reg(h, "cutover_task", "CT1", task_id="CT1", object_ids=["OBJ1"], owner="", duration_hours_likely=1, state="New")
    p = build_dod_gate(ctx(h, "dod.requested")).items[0].payload
    assert p["ready_for_sit"] is False and p["blockers"] == ["cutover tasks identified with owners and durations"]
