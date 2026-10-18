"""End-to-end Prepare flow through the HTTP API with a scripted LLM."""

from .conftest import PID, Harness, item

TRANSCRIPT = (
    "[00:01:10] Anna (Sales Manager): We handle roughly 2000 orders per day and every credit check is done manually.\n"
    "[00:05:40] Ben (AR Lead): The credit block rule also decides when dunning starts."
)


def test_transcript_to_register_with_human_gates(h: Harness):
    h.answer("Capture & Extraction Agent", [
        item("requirement_entry", "Manual credit checks", {"id": "REQ-O2C-01", "type": "pain_point", "process_area": "O2C",
             "as_is": "manual credit check", "volume_frequency": "2000 orders/day", "workshop_id": "W1", "urgency": "High"},
             quote="roughly 2000 orders per day and every credit check is done manually", speaker="Anna", ts="00:01:10"),
        item("requirement_entry", "Invented volume", {"id": "REQ-O2C-02"}, quote="we ship 50000 parcels a day"),
        item("requirement_entry", "No evidence at all", {"id": "REQ-O2C-03"}),
    ], questions=["What is the exception rate?"])
    h.answer("Cross-Process Impact Agent", [
        item("cross_team_flag", "Credit block drives dunning", {"id": "FLAG-1", "target_area": "FI-AR", "why": "credit block changes dunning",
             "source_workshop": "W1", "requirement_ids": ["REQ-O2C-01"]},
             quote="credit block rule also decides when dunning starts", speaker="Ben", ts="00:05:40")])

    lead = h.client("workshop_lead", "lead@x.com")
    pm = h.client("pm", "pm@x.com")
    assert lead.post(f"/v1/projects/{PID}/events", json={"type": "transcript.received", "payload": {
        "workshop_id": "W1", "process_area": "O2C", "transcript": TRANSCRIPT}}).status_code == 202

    props = pm.get(f"/v1/projects/{PID}/proposals", params={"kind": "requirement_entry"}).json()
    assert len(props) == 2  # the evidence-free item never became a proposal
    by_title = {p["title"]: p for p in props}
    assert by_title["Manual credit checks"]["flags"] == ["inferred"] or "quote_not_verified" not in by_title["Manual credit checks"]["flags"]
    assert "quote_not_verified" in by_title["Invented volume"]["flags"] and by_title["Invented volume"]["inferred"]
    assert by_title["Manual credit checks"]["payload"]["urgency_inferred"] is True
    assert pm.get(f"/v1/projects/{PID}/register", params={"kind": "requirement_entry"}).json() == []

    run = {r["agent_id"]: r for r in pm.get(f"/v1/projects/{PID}/runs").json()}
    assert run["prepare.capture_extraction"]["dropped"][0]["reason"] == "no_evidence"
    assert "prepare.cross_process_impact" in run  # fired from extraction.completed

    # the wrong role cannot decide; the workshop lead can
    cps = {c["proposal"]["kind"] + c["proposal"]["title"]: c for c in lead.get("/v1/checkpoints").json()}
    cp = cps["requirement_entryManual credit checks"]
    assert pm.post(f"/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"outcome": "approve"}).status_code == 403
    assert lead.post(f"/v1/checkpoints/{cp['checkpoint_id']}/decision", json={"outcome": "approve"}).status_code == 200
    reg = pm.get(f"/v1/projects/{PID}/register", params={"kind": "requirement_entry"}).json()
    assert [r["id"] for r in reg] == ["REQ-O2C-01"] and reg[0]["validated"]

    # reject the unverified one with a reason; the batch is now complete -> consolidation runs
    cp2 = cps["requirement_entryInvented volume"]
    assert lead.post(f"/v1/checkpoints/{cp2['checkpoint_id']}/decision", json={"outcome": "reject"}).status_code == 422
    assert lead.post(f"/v1/checkpoints/{cp2['checkpoint_id']}/decision",
                     json={"outcome": "reject", "reason": "not said in the workshop"}).status_code == 200
    run = {r["agent_id"] for r in pm.get(f"/v1/projects/{PID}/runs").json()}
    assert "prepare.consolidation_conflict" in run

    # PM raises the cross-team flag -> workshop request created
    flag_cp = next(c for k, c in cps.items() if k.startswith("cross_team_flag"))
    assert pm.post(f"/v1/checkpoints/{flag_cp['checkpoint_id']}/decision", json={"outcome": "approve"}).status_code == 200
    reqs = pm.get(f"/v1/projects/{PID}/register", params={"kind": "workshop_request"}).json()
    assert reqs and reqs[0]["target_area"] == "FI-AR"

    assert pm.get("/v1/audit/verify").json() == {"ok": True, "first_bad_seq": None}
    actions = {e["action"] for e in pm.get(f"/v1/projects/{PID}/audit").json()}
    assert {"agent.run.started", "proposal.created", "checkpoint.approve", "checkpoint.reject", "event.submitted"} <= actions


def test_api_access_rules(h: Harness):
    viewer, pm = h.client("viewer"), h.client("pm")
    body = {"type": "transcript.received", "payload": {}}
    assert viewer.post(f"/v1/projects/{PID}/events", json=body).status_code == 403
    assert pm.post(f"/v1/projects/{PID}/events", json={"type": "proposal.applied", "payload": {}}).status_code == 422
    assert pm.post(f"/v1/projects/{PID}/records/signoff", json={"id": "s1", "data": {}}).status_code == 201
    assert viewer.post(f"/v1/projects/{PID}/records/signoff", json={"id": "s2", "data": {}}).status_code == 403
    assert pm.post(f"/v1/projects/{PID}/records/requirement_entry", json={"id": "x", "data": {}}).status_code == 422
    other = h.client("pm")
    other.headers["X-Tenant-Id"] = "other"
    assert other.get(f"/v1/projects/{PID}/register").status_code == 404  # tenant isolation


def test_duplicate_event_is_processed_once(h: Harness):
    h.answer("Capture & Extraction Agent", [item("requirement_entry", "R", {"id": "REQ-1"}, quote="2000 orders per day")])
    lead = h.client("workshop_lead")
    ev = {"id": "evt-fixed", "type": "transcript.received", "payload": {"workshop_id": "W1", "transcript": TRANSCRIPT}}
    lead.post(f"/v1/projects/{PID}/events", json=ev)
    lead.post(f"/v1/projects/{PID}/events", json=ev)
    assert len(lead.get(f"/v1/projects/{PID}/proposals", params={"kind": "requirement_entry"}).json()) == 1
