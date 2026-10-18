"""The sandbox demo walks the whole dataset through the real platform; assert the story really happens."""

import pytest
from fastapi.testclient import TestClient

from auranexus.config import Settings
from auranexus.demo.app import create_app
from auranexus.demo.steps import STEPS


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def run_all(c: TestClient) -> None:
    for s in STEPS:
        if s.run:
            r = c.post(f"/demo/steps/{s.id}/run")
            assert r.status_code == 200, (s.id, r.text)
            assert all(run["status"] == "succeeded" for run in r.json()["runs"]), (s.id, r.json()["runs"])
        if s.human:
            r = c.post(f"/demo/steps/{s.id}/human")
            assert r.status_code == 200, (s.id, r.text)
            assert r.json()["performed"], (s.id, r.json()["skipped"])


def test_ui_and_script_are_served(client):
    assert client.get("/ui/").status_code == 200 and b"AuraNexus" in client.get("/ui/").content
    assert client.get("/ui/app.js").status_code == 200 and client.get("/ui/styles.css").status_code == 200
    sc = client.get("/demo/script").json()
    assert len(sc["steps"]) == len(STEPS) == 20 and {p["key"] for p in sc["personas"]} >= {"pm", "steering", "workshop_lead"}
    assert client.get("/", follow_redirects=False).status_code in (302, 307)


def test_full_story_end_to_end(client):
    run_all(client)
    view = client.get("/demo/view").json()
    reg = {k: v for k, v in view["register"].items()}
    props = {p["payload"].get("id") or p["id"]: p for p in view["proposals"]}

    # Phase 1: REQ-FI-019 captured at 64% then rejected by a human; the other three validated
    assert props["REQ-FI-019"]["confidence"] == 0.64 and props["REQ-FI-019"]["status"] == "rejected"
    reg_ids = {d["id"]: d for d in view["register_items"] if d["kind"] == "requirement_entry"}
    assert {"REQ-SD-042", "REQ-MM-015", "REQ-FI-008"} <= set(reg_ids)
    assert props["FLG-01"]["status"] == "applied" and props["FLG-02"]["status"] == "rejected" and props["FLG-03"]["status"] == "rejected"

    # Phase 2: KDD-FI-09 was modified (owner added) and approved with a warning; sentinel conflict raised; readiness gate says GO
    kdd = next(d for d in view["register_items"] if d["id"] == "KDD-FI-09")
    assert kdd["owner"] and "not assessed" in kdd["approval_note"]
    assert props["FLG-DSN-012"]["status"] == "applied"
    gate = next(p for p in view["proposals"] if p["kind"] == "gate_decision" and p["payload"]["gate"] == "design_readiness")
    assert gate["payload"]["recommendation"] == "go"

    # Phase 3: REQ-FI-019 unmapped in FS, REV-03 critical deferred (still open), DoD blocked, TC-SD-03 gap
    fs = props["FSGAP-01"]["payload"]["coverage_matrix"]
    assert any(r["requirement_id"] == "REQ-FI-019" and "Unmapped" in r["status"] for r in fs)
    assert props["REV-03"]["payload"]["severity"] == "Critical" and props["REV-03"]["status"] == "deferred"
    dod = next(p for p in view["proposals"] if p["kind"] == "dod_verdict")
    assert dod["payload"]["ready_for_sit"] is False and "traceability complete" not in dod["payload"]["blockers"]

    # Phase 4: no test links to REQ-FI-019; handoff notifications sent; escalation for TC-SD-03
    cases = [d for d in view["register_items"] if d["kind"] == "test_case"]
    assert {c["test_id"] for c in cases} == {"TC-SD-01", "TC-SD-02", "TC-SD-03"}
    assert not any("REQ-FI-019" in c.get("requirement_ids", []) for c in cases)
    subjects = " | ".join(n["subject"] for n in view["notifications"])
    assert "Ready for you: TC-SD-02" in subjects and "Ready for you: TC-SD-03" in subjects
    assess = next(p for p in view["proposals"] if p["kind"] == "phase_assessment")
    assert assess["payload"]["go_no_go_input"] == "no-go"

    # Phase 5: dry run fails, red scorecard with override, CP-DR1-014 tier 3 approved by two roles, loop closed
    score = next(p for p in view["proposals"] if p["kind"] == "scorecard")["payload"]
    assert score["rating"] == "Red" and any("data-integrity" in o for o in score["overrides_applied"]) and score["profile"] == "brownfield"
    assert any(n["severity"] == "critical" for n in view["notifications"])
    ref = next(p for p in view["proposals"] if p["kind"] == "refinement_proposal")
    assert ref["payload"]["proposal_id"] == "CP-DR1-014" and ref["payload"]["tier"] == 3 and ref["status"] == "applied"
    assert reg["guideline_version"] == 1 
    reinstated = next(d for d in view["register_items"] if d["id"] == "REQ-FI-019" and d["kind"] == "requirement_entry")
    assert reinstated["status"] == "reinstated" and reinstated["validated"]
    approvers = next(d for d in view["register_items"] if d["kind"] == "guideline_version")["approvers"]
    assert len(set(approvers)) == 2

    assert view["audit_ok"] is True and view["audit_total"] > 100
    thread = client.get("/demo/thread").json()
    assert [n["state"] for n in thread] == ["miss", "miss", "miss", "miss", "miss", "caught", "ok"]


def test_decisions_still_enforce_roles_in_the_ui_path(client):
    client.post("/demo/steps/p1-transcript/run")
    cp = next(c for c in client.get("/demo/view").json()["checkpoints"] if c["proposal"]["title"].startswith("Suppress dunning"))
    h = {"X-Tenant-Id": "acme", "X-Dev-User": "x@acme-demo.example", "X-Dev-Roles": "pm"}
    assert client.post(f"/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"outcome": "approve"}, headers=h).status_code == 403
    h["X-Dev-Roles"] = "workshop_lead"
    assert client.post(f"/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"outcome": "reject"}, headers=h).status_code == 422  # reason
    assert client.post(f"/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"outcome": "approve"}, headers=h).status_code == 200


def test_reset_restores_the_starting_state(client):
    run_all(client)
    assert client.post("/demo/reset").json() == {"status": "reset"}
    v = client.get("/demo/view").json()
    assert v["proposals"] == [] and v["register"] == {} and v["done"] == {}


def test_demo_mode_refuses_unsafe_combinations():
    with pytest.raises(RuntimeError):
        Settings(demo_mode=True, store_backend="postgres").validate_for_runtime()
    with pytest.raises(RuntimeError):
        Settings(demo_mode=True, llm_backend="gemini").validate_for_runtime()
    with pytest.raises(RuntimeError):
        Settings(demo_mode=True, env="prod").validate_for_runtime()
