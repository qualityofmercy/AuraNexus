"""Test-phase handoff and Run-phase scoring through the API (deterministic agents, no LLM)."""

from datetime import timedelta

from auranexus.domain.models import utcnow

from .conftest import PID, Harness


def iso(m: float) -> str:
    return (utcnow() + timedelta(minutes=m)).isoformat()


def test_tracker_approval_then_handoff_notifies_next_tester(h: Harness):
    lead, tester = h.client("test_lead", "tl@x.com"), h.client("tester", "anna@x.com")
    scripts = [
        {"test_id": "OTC-013", "scenario": "O2C", "step_owner": "anna", "requirement_ids": ["R1"]},
        {"test_id": "OTC-014", "scenario": "O2C", "step_owner": "ben", "predecessor_ids": ["OTC-013"]},
    ]
    assert lead.post(f"/v1/projects/{PID}/events", json={"type": "test.scripts.received", "payload": {"scripts": scripts}}).status_code == 202
    cp = lead.get("/v1/checkpoints").json()[0]
    assert cp["code"] == "T-TRK"
    assert tester.post(f"/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"outcome": "approve"}).status_code == 403
    assert lead.post(f"/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"outcome": "approve"}).status_code == 200
    cases = {c["test_id"]: c for c in lead.get(f"/v1/projects/{PID}/register", params={"kind": "test_case"}).json()}
    assert cases["OTC-013"]["status"] == "Ready" and cases["OTC-014"]["status"] == "Not Started"

    # the tester confirms completion -> next tester is notified automatically and the successor becomes Ready
    r = tester.post(f"/v1/projects/{PID}/records/test_case", json={"id": "OTC-013", "data": {
        **cases["OTC-013"], "status": "Passed", "produced": {"Sales Order": "4500012345"}}})
    assert r.status_code == 201
    sent = [n for n in h.c.bus.notifications if n.recipient == "ben"]
    assert len(sent) == 1 and "4500012345" in sent[0].body
    cases = {c["test_id"]: c for c in lead.get(f"/v1/projects/{PID}/register", params={"kind": "test_case"}).json()}
    assert cases["OTC-014"]["status"] == "Ready"

    xlsx = lead.get(f"/v1/projects/{PID}/exports/test-tracker.xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_scoring_requires_pm_decision_and_freezes_rubric(h: Harness):
    pm, cl = h.client("pm", "pm@x.com"), h.client("cutover_lead", "cl@x.com")
    base = -300
    cl.post(f"/v1/projects/{PID}/records/rehearsal", json={"id": "DR1", "data": {
        "name": "Dry Run 1", "window_start": iso(base), "window_end": iso(base + 120), "rollback_tested": True, "status": "complete"}})
    cl.post(f"/v1/projects/{PID}/records/rehearsal_task", json={"id": "DR1:T1", "data": {
        "rehearsal_id": "DR1", "task_id": "T1", "planned_start": iso(base), "planned_end": iso(base + 60), "actual_start": iso(base),
        "actual_end": iso(base + 60), "status": "completed", "predecessors": [], "owner": "o", "backup_owner": "b"}})
    cl.post(f"/v1/projects/{PID}/records/reconciliation", json={"id": "r", "data": {
        "rehearsal_id": "DR1", "reconciliation_pct": 100, "rejection_pct": 0, "resolved": True, "breach_pct": 0}})
    assert cl.post(f"/v1/projects/{PID}/events", json={"type": "rehearsal.completed", "payload": {"rehearsal_id": "DR1"}}).status_code == 202
    cp = next(c for c in pm.get("/v1/checkpoints").json() if c["code"] == "R-SCORE")
    sc = pm.get(f"/v1/checkpoints/{cp['checkpoint_id']}").json()["proposal"]
    assert sc["payload"]["rating"] in {"Green", "Amber", "Red"} and sc["payload"]["profile"] == "greenfield"
    assert pm.post(f"/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"outcome": "approve"}).status_code == 200
    assert pm.get(f"/v1/projects/{PID}/register", params={"kind": "scorecard"}).json()
    assert pm.get(f"/v1/projects/{PID}/register", params={"kind": "rubric_freeze"}).json()  # frozen at first scoring
    # analytics rows were emitted for dashboards
    assert {t for t, _ in h.c.analytics.rows} >= {"agent_runs", "hitl_decisions", "quality_scores"}
