"""The guided demo script: 20 steps across the five phases.

Each step either triggers real platform events (agents run, producing proposals), records human-authored facts
(through the same audited path as the API), or performs the human decisions at the checkpoints. "Suggested human
action" buttons perform the decision as the correct persona so a recording stays smooth; every decision can also be
made manually in the UI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..container import Container
from ..domain.models import DecisionOutcome, Event, Role, utcnow
from . import dataset as D

T, P = D.TENANT, D.PROJECT


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    title: str
    email: str
    roles: tuple[Role, ...]


PERSONAS: dict[str, Persona] = {p.key: p for p in [
    Persona("pm", "Priya Nair", "Project Manager", "priya.nair@acme-demo.example", (Role.PM,)),
    Persona("facilitator", "Fiona Dsouza", "Facilitator", "fiona.dsouza@acme-demo.example", (Role.FACILITATOR,)),
    Persona("workshop_lead", "Wes Menon", "Workshop Lead", "wes.menon@acme-demo.example", (Role.WORKSHOP_LEAD,)),
    Persona("functional_lead", "Farah Khan", "Functional Lead", "farah.khan@acme-demo.example", (Role.FUNCTIONAL_LEAD,)),
    Persona("technical_lead", "Tara Joshi", "Technical Lead", "tara.joshi@acme-demo.example", (Role.TECHNICAL_LEAD,)),
    Persona("test_lead", "Tejas Rao", "Test Lead", "tejas.rao@acme-demo.example", (Role.TEST_LEAD,)),
    Persona("tester", "Anna Sharma", "Tester", "anna.sharma@acme-demo.example", (Role.TESTER,)),
    Persona("cutover_manager", "Chitra Iyer", "Cutover Manager", "chitra.iyer@acme-demo.example", (Role.CUTOVER_MANAGER,)),
    Persona("steering", "Sam Verma", "Steering Committee", "sam.verma@acme-demo.example", (Role.STEERING,)),
]}


@dataclass
class HumanAction:
    persona: str
    kind: str
    outcome: DecisionOutcome
    pid: str = ""  # payload id (or "" = any item of that kind)
    reason: str = ""
    changes: dict[str, Any] = field(default_factory=dict)  # merged onto the proposal payload for MODIFY
    note: str = ""  # shown in the UI


@dataclass
class Step:
    id: str
    phase: int
    title: str
    story: str
    agents: list[str]
    run_label: str = ""
    run: Callable[[Container], None] | None = None
    human: list[HumanAction] = field(default_factory=list)
    human_label: str = ""
    insight: str = ""  # what to say on the recording


A, D_ = DecisionOutcome.APPROVE, DecisionOutcome


# ------------------------------------------------------------------------------------------------ helpers

def _iso(now: datetime, minutes: float) -> str:
    return (now + timedelta(minutes=minutes)).isoformat()


def record(c: Container, persona: str, kind: str, rid: str, data: dict[str, Any]) -> None:
    """Human-authored fact, same audited path as POST /records/{kind}."""
    p = PERSONAS[persona]
    prev = c.repo.register_get(T, kind, rid) or {}
    c.repo.register_put(T, P, kind, rid, {**prev, **data, "recorded_by": p.email})
    c.repo.audit.record(T, P, p.email, "human", "record.revised" if prev else "record.written", kind, rid, {})


def emit(c: Container, etype: str, payload: dict[str, Any] | None = None) -> None:
    c.bus.publish(Event(tenant_id=T, project_id=P, type=etype, payload=payload or {}))


def seed(c: Container) -> None:
    from ..domain.models import Project, ProjectType

    c.repo.register_tenant(T)
    c.repo.put_project(Project(id=P, tenant_id=T, name=D.PROJECT_NAME, project_type=ProjectType.BROWNFIELD,
                               settings={"refinement_seq_start": 14, "demo": True}))
    c.repo.audit.record(T, P, "system", "system", "project.created", "project", P, {"project_type": "brownfield"})


# ------------------------------------------------------------------------------------------------ runners

def p1_brief(c: Container) -> None:
    record(c, "pm", "workshop", D.WORKSHOP_ID, {"process_area": "SD-FI", "status": "planned", "duration_hours": 3,
                                                 "attendee_roles": ["sales_manager", "ar_lead"], "requirement_ids": []})
    emit(c, "workshop.scheduled", {"workshop_id": D.WORKSHOP_ID, "process_area": "SD-FI", "attendee_roles": ["sales_manager", "ar_lead"]})


def p1_transcript(c: Container) -> None:
    record(c, "facilitator", "workshop", D.WORKSHOP_ID, {"status": "held"})
    emit(c, "transcript.received", {"workshop_id": D.WORKSHOP_ID, "process_area": "SD-FI",
                                    "attendees": [{"name": "Priya", "role": "credit_manager"}, {"name": "Marco", "role": "procurement_lead"},
                                                  {"name": "Anita", "role": "ar_lead"}, {"name": "Ravi", "role": "gl_lead (dial-in, poor audio)"}],
                                    "transcript": D.PREP_TRANSCRIPT})


def p1_weekly(c: Container) -> None:
    emit(c, "schedule.weekly")


def p2_scribe(c: Container) -> None:
    record(c, "pm", "workshop", "W-DSN-01", {"process_area": "Design", "status": "held", "requirement_ids": ["REQ-SD-042", "REQ-FI-008"]})
    emit(c, "design.transcript.received", {"workshop_id": "W-DSN-01", "transcript": D.DESIGN_TRANSCRIPT})


def p2_gate(c: Container) -> None:
    for kdd, who in (("KDD-FI-04", "FI Lead"), ("KDD-SD-12", "SD Lead"), ("KDD-FI-09", "FI Lead")):
        record(c, "pm", "signoff", f"SO-{kdd}", {"decision_id": kdd, "stakeholder": who, "role": "process owner", "status": "approved", "internal": True})
    record(c, "pm", "workshop", D.WORKSHOP_ID, {"requirement_ids": ["REQ-SD-042", "REQ-MM-015"]})
    emit(c, "gate.design_readiness.requested")


def p3_fs(c: Container) -> None:
    emit(c, "fs.requested", {"mode": "review", "title": "Z_DUNNING_EXT dunning suppression", "fs_text": D.FS_TEXT,
                             "requirement_ids": ["REQ-SD-042", "REQ-FI-019"]})


def p3_review(c: Container) -> None:
    emit(c, "review.requested", {"review_mode": "fs", "artifact": D.FS_TEXT, "tool_results": {}})
    emit(c, "review.requested", {"review_mode": "code", "artifact": D.ABAP_TEXT,
                                 "tool_results": {"atc": [{"check": "SELECT in loop", "object": "Z_DUNNING_EXT", "priority": 2}]}})


def p3_tests(c: Container) -> None:
    emit(c, "tests.requested", {"requirement_ids": ["REQ-SD-042"], "fs_text": D.FS_TEXT})


def p3_dod(c: Container) -> None:
    record(c, "technical_lead", "ricefw_object", "OBJ-DUN-EXT", {
        "requirement_ids": ["REQ-SD-042"], "fs_ids": ["FS-4.1", "FS-4.3"], "ts_ids": ["TS-DUN-01"], "code_objects": ["Z_DUNNING_EXT"],
        "test_case_ids": ["TC-SD-01", "TC-SD-02"], "fs_status": "in_review", "ts_status": "approved", "code_review_verdict": "Fail",
        "atc_clean": False, "unit_tests_executed": True, "coverage_pct": 60, "rubric_score": 58, "transport_notes_complete": True})
    emit(c, "dod.requested", {"object_id": "OBJ-DUN-EXT"})


def p4_tracker(c: Container) -> None:
    now = utcnow()
    scripts = []
    for s in D.TEST_SCRIPTS:
        s = dict(s)
        for k in ("planned_start", "planned_end"):
            s[k] = _iso(now, float(s[k].strip("{}h")) * 60)
        scripts.append(s)
    emit(c, "test.scripts.received", {"scripts": scripts})


def _status(c: Container, test_id: str, status: str, produced: dict[str, str] | None = None) -> None:
    cur = c.repo.register_get(T, "test_case", test_id) or {}
    record(c, "tester", "test_case", test_id, {**cur, "status": status})
    emit(c, "test.status.updated", {"test_id": test_id, "status": status, "actor": PERSONAS["tester"].email, "produced": produced or {}})


def p4_exec(c: Container) -> None:
    _status(c, "TC-SD-01", "Passed", {"Credit-blocked sales order": "4500012345"})
    _status(c, "TC-SD-02", "Passed", {"Comparison sales order": "4500012346"})
    emit(c, "schedule.hourly")  # TC-SD-03 became ready 3h ago and nobody started it: nudge and escalate


def p4_assess(c: Container) -> None:
    emit(c, "test.assess.requested", {"phase": "end"})


def _dr_base() -> datetime:
    return utcnow() - timedelta(minutes=300)


def p5_dryrun(c: Container) -> None:
    t0 = _dr_base()
    record(c, "cutover_manager", "rehearsal", "DR1", {"name": "Dry Run 1", "status": "in_progress", "window_start": _iso(t0, 0),
                                                       "window_end": _iso(t0, 120), "rollback_tested": True})
    tasks = [
        ("TSK-FI-088", "Execute customer master & credit risk data load", 0, 45, 90, 225, "completed", [], "Data Migration Lead", "Basis Lead", False),
        ("TSK-SD-104", "Maintain SD credit control area configuration", 0, 30, 0, 30, "completed", [], "Lead - SD Consultant", "SD Analyst", False),
        ("TSK-FI-112", "Multi-currency invoice reconciliation balance check post-load", 45, 60, 225, 240, "failed",
         ["TSK-FI-088", "TSK-SD-104"], "Financial Controller", "", True),
    ]
    for tid, desc, ps, pe, as_, ae, status, pre, owner, backup, rb in tasks:
        record(c, "cutover_manager", "rehearsal_task", f"DR1:{tid}", {
            "rehearsal_id": "DR1", "task_id": tid, "name": desc, "planned_start": _iso(t0, ps), "planned_end": _iso(t0, pe),
            "actual_start": _iso(t0, as_), "actual_end": _iso(t0, ae), "status": status, "predecessors": pre, "owner": owner,
            "backup_owner": backup, "rollback_point": rb, "target_environment": "QAS / PROD"})
    record(c, "cutover_manager", "reconciliation", "REC-DR1-112", {
        "rehearsal_id": "DR1", "object": "Multi-currency open invoices", "reconciliation_pct": 96.8, "rejection_pct": 0.0,
        "resolved": False, "breach_pct": 3.2, "variance_inr": 1420000, "error_report": "ERR-FIN-99"})
    record(c, "cutover_manager", "defect", "DEF-DR1-01", {
        "rehearsal_id": "DR1", "severity": "critical", "status": "open", "summary": "Multi-currency reconciliation discrepancy INR 1,420,000",
        "opened": _iso(t0, 240), "repeat": False})
    emit(c, "rehearsal.actuals.updated", {"rehearsal_id": "DR1"})


def p5_notes(c: Container) -> None:
    emit(c, "rehearsal.notes.received", {"rehearsal_id": "DR1", "notes": D.NOTES})


def p5_score(c: Container) -> None:
    record(c, "cutover_manager", "rehearsal", "DR1", {"status": "complete", "actual_window_hours": 4.0})
    emit(c, "rehearsal.completed", {"rehearsal_id": "DR1", "rehearsal_code": "DR1"})


# ------------------------------------------------------------------------------------------------ the script

STEPS: list[Step] = [
    # -------- Phase 1
    Step("p1-brief", 1, "Pre-workshop briefing", agents=["Workshop Prep Agent"],
         story="The workshop is scheduled. The Workshop Prep Agent builds a facilitator briefing from what the register already knows, the accelerator library and the interdependency map.",
         run_label="Schedule workshop W-FI-01", run=p1_brief,
         human=[HumanAction("facilitator", "workshop_briefing", A, note="Facilitator reviews and accepts the briefing (CP0)")],
         human_label="Facilitator accepts briefing",
         insight="Note the role gap: the GL lead is not on the attendee list, even though dunning and credit rules post to the ledger."),
    Step("p1-transcript", 1, "Workshop transcript → Capture & Extraction", agents=["Capture & Extraction Agent", "Cross-Process Impact Agent", "Template Steward Agent"],
         story="The meeting tool delivers the transcript. The agent segments it into register entries with verbatim evidence, quote-checks everything against the transcript, and the Cross-Process Agent scans each entry against the interdependency map.",
         run_label="Deliver transcript", run=p1_transcript,
         insight="Four entries, each with a verbatim quote, timestamp and speaker. REQ-FI-019 comes from garbled audio: the agent flags it with only 64% confidence."),
    Step("p1-cp1", 1, "CP1: human validation of extracted entries", agents=[],
         story="Nothing is in the register yet. The workshop lead validates each entry. This is where a human decision can still go wrong.",
         human=[HumanAction("workshop_lead", "requirement_entry", A, "REQ-SD-042", note="Confirm"),
                HumanAction("workshop_lead", "requirement_entry", A, "REQ-MM-015", note="Confirm"),
                HumanAction("workshop_lead", "requirement_entry", A, "REQ-FI-008", note="Confirm"),
                HumanAction("workshop_lead", "requirement_entry", D_.REJECT, "REQ-FI-019",
                            "Audio too unclear to confirm what was said; cannot validate this one.", note="Reject (the injected error)")],
         human_label="Workshop lead decides (rejects REQ-FI-019)",
         insight="The rejection is logged with a reason, but the multi-currency rounding requirement has now silently left the project."),
    Step("p1-cp3", 1, "CP3: cross-team flags", agents=[],
         story="The PM raises or dismisses each cross-team flag. Accepting a flag creates a workshop request.",
         human=[HumanAction("pm", "cross_team_flag", A, "FLG-01", note="Raise: credit block vs dunning"),
                HumanAction("pm", "cross_team_flag", D_.REJECT, "FLG-02", "Weight units are a logistics master-data topic for the MM track.", note="Dismiss with reason"),
                HumanAction("pm", "cross_team_flag", D_.REJECT, "FLG-03", "Rebates are covered in the pricing workshop; no cross-check needed.",
                            note="Dismiss prematurely (second injected error)")],
         human_label="PM raises FLG-01, dismisses FLG-02 and FLG-03",
         insight="FLG-03 (rebates tied to credit limits) is dismissed without a cross-check: a false negative the audit trail will remember."),
    Step("p1-weekly", 1, "Weekly quality score and summary", agents=["Monitor & Quality Agent (Prepare)"],
         story="The weekly tick scores workshop W-FI-01 on the eight-dimension rubric (deterministic maths, not the model) and drafts the weekly summary.",
         run_label="Run weekly tick", run=p1_weekly,
         human=[HumanAction("pm", "weekly_summary", A, note="PM signs off the summary (CP5)")], human_label="PM signs off the weekly summary",
         insight="The score reflects what the register contains: it cannot see a requirement that was never captured."),
    # -------- Phase 2
    Step("p2-scribe", 2, "Design session → Design Scribe + Sentinel", agents=["Design Scribe", "Cross-Functional Sentinel"],
         story="Design sessions are transcribed into decisions, assumptions and development objects. The Sentinel then compares decisions across parallel tracks.",
         run_label="Deliver design transcript", run=p2_scribe,
         insight="KDD-FI-09 has no owner (the mandatory-field check lists it as needing attention) and rests on the assumption of zero minor-currency discrepancies."),
    Step("p2-review", 2, "Review design register entries", agents=[],
         story="The workshop lead validates entries. For KDD-FI-09 they add the missing owner and an approval note, but the missing impact is not caught.",
         human=[HumanAction("workshop_lead", "decision", A, "KDD-FI-04"), HumanAction("workshop_lead", "decision", A, "KDD-SD-12"),
                HumanAction("workshop_lead", "decision", D_.MODIFY, "KDD-FI-09", "Owner was blank; added. Approved with warning.",
                            changes={"owner": "Sofia (FI Lead)", "approval_note": "Approved with warning: multi-currency rounding impact not assessed."},
                            note="Modify: add owner, approve with warning"),
                HumanAction("workshop_lead", "assumption", A, "A-01"), HumanAction("workshop_lead", "dev_object", A, "OBJ-DUN-EXT")],
         human_label="Workshop lead validates (modifies KDD-FI-09)",
         insight="'Modify' lets a human correct an agent's proposal; the original and the edit are both in the audit trail."),
    Step("p2-sentinel", 2, "Sentinel conflict: dunning vs shipping", agents=[],
         story="The Sentinel found that Finance and Sales & Distribution assume opposite handling of credit-blocked orders. The PM raises it; a joint session request is created.",
         human=[HumanAction("pm", "sentinel_flag", A, "FLG-DSN-012", note="Raise and request the joint FI-AR/SD session")],
         human_label="PM raises FLG-DSN-012",
         insight="This cross-track contradiction was caught. The currency gap was not, because the Sentinel only sees what is in the register."),
    Step("p2-gate", 2, "Design readiness gate", agents=["Monitor, Re-planner and Readiness Gate"],
         story="Sign-offs are recorded by humans (agents never record sign-offs). The deterministic readiness gate checks coverage, conflicts, mandatory fields, sign-offs, assumptions and dependencies.",
         run_label="Record sign-offs and run the gate", run=p2_gate,
         human=[HumanAction("pm", "gate_decision", A, note="PM accepts the gate result")], human_label="PM accepts the gate decision",
         insight="GO. Every check passes, because the missing requirement is not in the register to be checked. The error has slipped past an early gate."),
    # -------- Phase 3
    Step("p3-fs", 3, "FS coverage review", agents=["FS Gap Analyzer and FS Starter"],
         story="The FS Gap Analyzer maps each requirement to FS sections and lists gaps.",
         run_label="Review the FS", run=p3_fs,
         human=[HumanAction("functional_lead", "fs_gap_report", A, note="Functional lead accepts the report")], human_label="Functional lead accepts the report",
         insight="REQ-FI-019 shows as Unmapped (Missed). The report is accepted, but no one is assigned to act on that row."),
    Step("p3-review", 3, "Code and FS review", agents=["Review Agent (FS, TS, Code)"],
         story="The Review Agent reports findings with severity, rule id and verbatim evidence, then a verdict. The critical hardcoded-currency finding is deferred by a human.",
         run_label="Review FS and ABAP", run=p3_review,
         human=[HumanAction("technical_lead", "review_finding", A, "REV-01"), HumanAction("technical_lead", "review_finding", A, "REV-02"),
                HumanAction("technical_lead", "review_finding", D_.DEFER, "REV-03", "Hardcoded rate acceptable for now; fix in the hardening sprint.", note="Defer the critical finding"),
                HumanAction("technical_lead", "review_verdict", A, "RV-FS"), HumanAction("technical_lead", "review_verdict", A, "RV-CODE")],
         human_label="Technical lead decides (defers REV-03)",
         insight="REV-03 (critical) is deferred, not fixed. The checkpoint stays open with a deadline, but the hardcoded conversion ships forward."),
    Step("p3-tests", 3, "Unit test generation", agents=["Test Case (TUT) Generator and Coverage Checker"],
         story="Tests are derived from requirements and the FS, not from the code. The agent also reports coverage gaps.",
         run_label="Generate tests", run=p3_tests,
         human=[HumanAction("functional_lead", "unit_test_case", A, "TC-SD-01"), HumanAction("functional_lead", "unit_test_case", A, "TC-SD-02"),
                HumanAction("functional_lead", "coverage_gap", A, "TC-SD-03", note="Acknowledge the missing authorization test")],
         human_label="Functional lead accepts tests and the gap",
         insight="No test for REQ-FI-019 can be generated: the requirement never reached the FS or the register."),
    Step("p3-dod", 3, "Definition-of-Done gate", agents=["Definition of Done Gate"],
         story="Before an object moves to SIT, the deterministic DoD gate checks FS/TS approval, review verdict, ATC, coverage, traceability and cutover tasks.",
         run_label="Run the DoD gate", run=p3_dod,
         human=[HumanAction("pm", "dod_verdict", A, note="PM acknowledges the blocked verdict")], human_label="PM acknowledges",
         insight="The gate blocks the dunning object on several counts, but it can only judge objects that are in the register."),
    # -------- Phase 4
    Step("p4-tracker", 4, "TestStarter tracker + dependency analysis", agents=["TestStarter", "Dependency and Sequencer"],
         story="TestStarter builds the tracking workbook. After approval the Dependency Sequencer classifies dependencies and the platform computes waves and the critical path.",
         run_label="Submit test scripts", run=p4_tracker,
         human=[HumanAction("test_lead", "test_tracker", A, note="Approve the tracker"),
                HumanAction("test_lead", "test_dependency", A, note="Approve dependencies"),
                HumanAction("test_lead", "blocker_risk", A), HumanAction("test_lead", "test_sequence", A, note="Approve execution plan")],
         human_label="Test lead approves tracker and plan",
         insight="Download the Excel tracker from the Test section. Notice there is no TC-FI-09: the multi-currency test was never created."),
    Step("p4-exec", 4, "Execution, handoffs and nudges", agents=["Handoff and Progress Orchestrator"],
         story="Testers confirm completion; the next tester is notified automatically. Hourly, delayed starts are nudged and escalated.",
         run_label="Testers complete TC-SD-01 and TC-SD-02", run=p4_exec,
         human=[HumanAction("test_lead", "test_escalation", A, note="Test lead acts on the escalation")], human_label="Test lead handles the escalation",
         insight="Open the notifications panel: the handoff message names the document numbers produced by the predecessor."),
    Step("p4-assess", 4, "End-of-phase readiness assessment", agents=["Coverage and Readiness Assessor"],
         story="The assessor checks coverage per requirement and the exit criteria.",
         run_label="Assess readiness", run=p4_assess,
         human=[HumanAction("test_lead", "phase_assessment", A, note="Accept the assessment")], human_label="Test lead accepts the assessment",
         insight="No-go: the authorization test never ran. The multi-currency defect is not visible, because REQ-FI-019 is not in the register."),
    # -------- Phase 5
    Step("p5-dryrun", 5, "Dry Run 1: live monitoring", agents=["Execution Monitor Agent"],
         story="Dry Run 1 executes. The Execution Monitor is read-only: it computes variance, recalculates the critical path and alerts on window risk.",
         run_label="Load Dry Run 1 actuals", run=p5_dryrun,
         insight="TSK-FI-088 planned 45 minutes, took 2h15m and started 90 minutes late. TSK-FI-112 failed. Critical alert raised."),
    Step("p5-notes", 5, "Bridge-call notes → Observation Logger", agents=["Observation Logger"],
         story="The Observation Logger records what went smoothly and what did not, each with evidence.",
         run_label="Deliver bridge notes", run=p5_notes,
         insight="Positives are logged as deliberately as problems: TSK-SD-104 is the pattern to keep."),
    Step("p5-score", 5, "Scorecard and Refinement Advisor", agents=["Scoring Agent", "Refinement Advisor Agent"],
         story="The Scoring Agent applies the frozen rubric and override rules. The Refinement Advisor turns the findings into a change proposal and the platform assigns its tier and id.",
         run_label="Close Dry Run 1 and score", run=p5_score,
         human=[HumanAction("pm", "scorecard", A, note="PM signs off the scorecard")], human_label="PM signs off the scorecard",
         insight="Red: the data-integrity override caps the rating regardless of the weighted total."),
    Step("p5-approve", 5, "Tier-3 approval closes the loop", agents=["HITL Gatekeeper", "Guideline Steward"],
         story="CP-DR1-014 is a high-risk correction, so it needs two approvers in distinct roles: the PM and the Steering Committee. Only then does the Guideline Steward publish a new version.",
         human=[HumanAction("pm", "refinement_proposal", A, note="First approval (PM)"),
                HumanAction("steering", "refinement_proposal", A, note="Second approval (Steering Committee)")],
         human_label="PM and Steering Committee approve",
         insight="One approval is not enough. After the second, REQ-FI-019 is re-injected and the guideline library moves to a new version."),
]
STEP_BY_ID = {s.id: s for s in STEPS}
