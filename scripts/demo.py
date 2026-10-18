"""In-process demo of the Prepare flow with a scripted LLM (no GCP needed).

    python scripts/demo.py

Shows: transcript -> agent proposals (with guardrail flags) -> human decisions -> register -> audit chain.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auranexus.config import Settings  # noqa: E402
from auranexus.container import build_container  # noqa: E402
from auranexus.core.llm import FakeLLM  # noqa: E402
from auranexus.domain.models import DecisionOutcome, Event, Project, ProjectType, Role  # noqa: E402

TRANSCRIPT = """[00:01:10] Anna (Sales Manager): We handle roughly 2000 orders per day and every credit check is done manually.
[00:05:40] Ben (AR Lead): The credit block rule also decides when dunning starts."""


def scripted(system: str, user: str) -> dict:
    def ev(q, spk, ts):
        return [{"quote": q, "timestamp": ts, "speaker": spk, "source_ref": "W1"}]

    if "SKILL: Capture & Extraction Agent" in system:
        items = [
            {"kind": "requirement_entry", "title": "Manual credit checks", "confidence": 0.85, "inferred": False,
             "payload_json": json.dumps({"id": "REQ-O2C-01", "type": "pain_point", "process_area": "O2C", "workshop_id": "W1",
                                         "as_is": "credit checks are manual", "volume_frequency": "2000 orders/day", "urgency": "High"}),
             "evidence": ev("roughly 2000 orders per day and every credit check is done manually", "Anna", "00:01:10")},
            {"kind": "requirement_entry", "title": "Hallucinated parcel volume", "confidence": 0.9, "inferred": False,
             "payload_json": json.dumps({"id": "REQ-O2C-02"}), "evidence": ev("we ship 50000 parcels a day", "Anna", "00:02:00")},
        ]
        return {"items": items, "open_questions": ["What is the exception rate?"], "notes": ""}
    if "SKILL: Cross-Process Impact Agent" in system:
        item = {"kind": "cross_team_flag", "title": "Credit block drives dunning (FI-AR)", "confidence": 0.8, "inferred": False,
                "payload_json": json.dumps({"id": "FLAG-1", "target_area": "FI-AR", "why": "credit block changes dunning",
                                            "risk_if_not_discussed": "dunning configured on wrong assumptions"}),
                "evidence": ev("credit block rule also decides when dunning starts", "Ben", "00:05:40")}
        return {"items": [item], "open_questions": [], "notes": ""}
    return {"items": [], "open_questions": [], "notes": ""}


def main() -> None:
    c = build_container(Settings(env="local"), llm=FakeLLM(scripted))
    t, p = "demo", "prj"
    c.repo.register_tenant(t)
    c.repo.put_project(Project(id=p, tenant_id=t, name="Demo", project_type=ProjectType.GREENFIELD))

    print("1) transcript arrives -> agents run")
    c.bus.publish(Event(tenant_id=t, project_id=p, type="transcript.received",
                        payload={"workshop_id": "W1", "process_area": "O2C", "transcript": TRANSCRIPT}))
    for r in c.repo.list_runs(t, p):
        print(f"   {r['agent_id']:<36} {r['status']:<10} proposals={len(r['proposals'])} dropped={r['dropped']}")

    print("\n2) open human checkpoints")
    for cp in c.orchestrator.open_checkpoints(t, p):
        pr = cp["proposal"]
        print(f"   [{cp['code']}] {pr['title']:<42} flags={pr['flags']} approvers={cp['approver_roles']}")

    print("\n3) humans decide")
    for cp in c.orchestrator.open_checkpoints(t, p):
        pr, role = cp["proposal"], Role(cp["approver_roles"][0])
        if "Hallucinated" in (pr["title"] or ""):
            c.hitl.decide(t, cp["checkpoint_id"], "lead@acme.com", [role], DecisionOutcome.REJECT, "not said in the workshop")
            print(f"   rejected  : {pr['title']}")
        else:
            c.hitl.decide(t, cp["checkpoint_id"], "lead@acme.com", [role], DecisionOutcome.APPROVE)
            print(f"   approved  : {pr['title']}")

    print("\n4) register (only human-approved content)")
    for kind in ("requirement_entry", "cross_team_flag", "workshop_request"):
        for d in c.repo.register_list(t, p, kind):
            print(f"   {kind:<18} {d['id']:<12} {d.get('status')}")

    ok, bad = c.repo.audit.verify(t)
    print(f"\n5) audit chain: {len(c.repo.store.list_audit(t))} entries, intact={ok}")


if __name__ == "__main__":
    main()
