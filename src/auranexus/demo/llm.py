"""Scripted stand-in for the model in the sandbox demo.

Each responder returns exactly what an LLM agent would emit for the dataset (including its deliberate misses). The
platform around it is real: schema normalisation, guardrails (evidence, quote verification, kind whitelists),
post-processing tools, HITL, appliers and audit all run on this output exactly as they would on Gemini's.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..core.llm import LLMResult
from . import dataset as D


def ev(quote: str = "", speaker: str = "", ts: str = "", ref: str = "") -> dict[str, str]:
    return {"quote": quote, "timestamp": ts, "speaker": speaker, "source_ref": ref}


def item(kind: str, title: str, payload: dict, evidence: list[dict], conf: float = 0.9, inferred: bool = False) -> dict:
    return {"kind": kind, "title": title, "payload_json": json.dumps(payload), "evidence": evidence,
            "confidence": conf, "inferred": inferred}


# ---------------------------------------------------------------------------------------------- Phase 1

def workshop_prep(p: dict) -> list[dict]:
    return [item("workshop_briefing", "Briefing: SD/FI credit-block and dunning workshop", {
        "workshop_id": p.get("workshop_id"), "process_area": p.get("process_area"),
        "already_captured": [],
        "empty_mandatory_fields": ["sub_process", "volume_frequency", "owner", "priority"],
        "prioritised_questions": [
            {"question": "How are credit blocks released today and who owns the release?", "why": "Drives dunning behaviour", "source": "accelerator O2C"},
            {"question": "Which pricing procedures and condition types are custom?", "why": "Conversion scope", "source": "accelerator O2C"},
            {"question": "Which parallel ledgers and currencies are required?", "why": "FI-GL touches every posting", "source": "accelerator R2R"}],
        "open_items": [],
        "role_gaps": ["GL lead (FI-GL) is not on the attendee list although dunning and credit rules post to the ledger"],
        "adjacent_asks": [],
    }, [ev(ref="accelerator_library:O2C"), ev(ref="interdependency_map:SD->FI-AR")], 0.85)]


def capture(p: dict) -> list[dict]:
    w = D.WORKSHOP_ID
    base = {"workshop_id": w}
    return [
        item("requirement_entry", "Suppress dunning during credit block review", {
            **base, "id": "REQ-SD-042", "type": "requirement", "process_area": "SD / FI", "sub_process": "Credit management",
            "as_is": "Customers on credit-block review still receive dunning letters", "to_be": "No dunning notices while a credit block review is active",
            "business_impact": "Customer friction and escalation calls", "volume_frequency": "approx. 40 affected customers per month",
            "priority": "Must", "owner": "Priya (Credit Manager)", "urgency": "High", "impacted_areas": ["FI-AR", "SD"]},
             [ev(D.Q["SD042"], "Priya", "00:02:10")], 0.98),
        item("requirement_entry", "Manual 3-way matching under $10k", {
            **base, "id": "REQ-MM-015", "type": "pain_point", "process_area": "MM / FI", "sub_process": "Invoice verification",
            "as_is": "Manual 3-way matching for purchase orders under $10k", "to_be": "Automated matching within tolerance",
            "business_impact": "Invoice processing bottlenecks at month end", "volume_frequency": "approx. 1,200 invoices per month",
            "priority": "Should", "owner": "Marco (Procurement Lead)", "urgency": "Medium", "impacted_areas": ["FI-AP"]},
             [ev(D.Q["MM015"], "Marco", "00:09:45")], 0.92),
        item("requirement_entry", "Retain legacy dunning rules and exemption lists", {
            **base, "id": "REQ-FI-008", "type": "constraint", "process_area": "FI-AR", "sub_process": "Dunning",
            "as_is": "Legacy dunning rules and custom exemption lists in production", "to_be": "Same rules and lists retained after conversion",
            "business_impact": "Regulatory and customer-agreement exposure if dropped", "volume_frequency": "all dunning runs",
            "priority": "Must", "owner": "Anita (AR Lead)", "urgency": "High", "impacted_areas": ["SD"]},
             [ev(D.Q["FI008"], "Anita", "00:17:30")], 0.95),
        item("requirement_entry", "Multi-currency tax translation rounding (unclear audio)", {
            **base, "id": "REQ-FI-019", "type": "requirement", "process_area": "FI-GL", "sub_process": "Tax / currency translation",
            "as_is": "Rounding rules for tax translation when posting in multiple currencies (audio unclear)",
            "to_be": "", "business_impact": "", "volume_frequency": "", "priority": "", "owner": "Ravi (GL Lead)", "urgency": "Low",
            "impacted_areas": ["FI-AR", "SD"]},
             [ev(D.Q["FI019"], "Ravi", "00:41:12")], 0.64, True),
    ]


def cross_process(p: dict) -> list[dict]:
    return [
        item("cross_team_flag", "Credit block rule change alters automated dunning (FI-AR <-> SD)", {
            "id": "FLG-01", "source_workshop": D.WORKSHOP_ID, "requirement_ids": ["REQ-SD-042", "REQ-FI-008"], "target_area": "SD",
            "why": "Credit block rule change directly alters the automated dunning schedule.",
            "risk_if_not_discussed": "Dunning configuration built on wrong assumptions, leading to unlawful customer chase letters.",
            "suggested_action": "Add a joint FI-AR / SD session", "suggested_attendee": "AR Lead and SD Lead", "dependency_type": "process"},
             [ev(D.Q["FLG01a"], "Priya", "00:02:10"), ev(D.Q["FLG01b"], "Anita", "00:17:30")], 0.9),
        item("cross_team_flag", "Material master weight unit mismatch across plants (MM <-> LE)", {
            "id": "FLG-02", "source_workshop": D.WORKSHOP_ID, "requirement_ids": [], "target_area": "LE",
            "why": "Material master weight unit mismatch across cross-border plant transfers.",
            "risk_if_not_discussed": "Customs declaration errors and freight calculation failures.",
            "suggested_action": "Check with Logistics", "suggested_attendee": "Logistics Lead", "dependency_type": "data"},
             [ev(D.Q["FLG02"], "Marco", "00:13:05")], 0.8),
        item("cross_team_flag", "Customer rebate agreements linked to credit limits (SD <-> SD-MD pricing)", {
            "id": "FLG-03", "source_workshop": D.WORKSHOP_ID, "requirement_ids": ["REQ-SD-042"], "target_area": "SD-MD",
            "why": "Special customer-specific rebate agreements linked to credit limits.",
            "risk_if_not_discussed": "Incorrect net pricing calculation on billed invoices post-conversion.",
            "suggested_action": "Cross-check with the pricing track", "suggested_attendee": "Pricing Lead", "dependency_type": "data"},
             [ev(D.Q["FLG03"], "Priya", "00:25:50")], 0.75),
    ]


# ---------------------------------------------------------------------------------------------- Phase 2

def scribe(p: dict) -> list[dict]:
    wid = "W-DSN-01"
    return [
        item("decision", "KDD-FI-04 Automated daily dunning execution", {
            "id": "KDD-FI-04", "description": "Implement automated daily dunning execution via the standard S/4 job.",
            "rationale": "Reduces manual accounting effort and accelerates cash collection.", "requirement_ids": ["REQ-FI-008"],
            "workshop_id": wid, "impacted_tracks": ["FI", "SD"], "owner": "Sofia (FI Lead)", "fit_gap": "fit", "status": "proposed"},
             [ev(D.DQ["KDD04"], "Sofia", "00:05:20")], 0.95),
        item("decision", "KDD-SD-12 No manual credit-block lifting in the UI", {
            "id": "KDD-SD-12", "description": "Sales representatives will not manually lift credit blocks via UI; rely on batch release rules.",
            "rationale": "Streamlines order fulfillment workflow.", "requirement_ids": ["REQ-SD-042"], "workshop_id": wid,
            "impacted_tracks": ["SD", "MM"], "owner": "Dev (SD Lead)", "fit_gap": "fit", "status": "proposed"},
             [ev(D.DQ["KDD12"], "Dev", "00:12:40")], 0.93),
        item("decision", "KDD-FI-09 Standard exchange-rate translation, no rounding logic", {
            "id": "KDD-FI-09", "description": "Use standard exchange rate translation without multi-currency rounding logic, assuming zero minor-currency discrepancies.",
            "rationale": "Simplifies technical build scope.", "requirement_ids": [], "workshop_id": wid,
            "impacted_tracks": ["FI", "SD"], "owner": "", "fit_gap": "fit", "status": "proposed"},
             [ev(D.DQ["KDD09"], "Sofia", "00:21:15")], 0.9),
        item("assumption", "A-01 No minor-currency discrepancies", {
            "id": "A-01", "statement": "Zero minor-currency discrepancies, so no rounding logic is required.", "owner": "Sofia (FI Lead)",
            "validation_due": "2026-12-15", "critical": True, "decision_id": "KDD-FI-09", "status": "open"},
             [ev(D.DQ["A01"], "Sofia", "00:21:15")], 0.85, True),
        item("dev_object", "Z_DUNNING_EXT dunning suppression enhancement", {
            "id": "OBJ-DUN-EXT", "name": "Z_DUNNING_EXT", "type": "enhancement", "complexity": "medium",
            "requirement_ids": ["REQ-SD-042"], "decision_ids": ["KDD-FI-04", "KDD-SD-12"], "prerequisites": [], "scope_status": "proposed"},
             [ev(ref="KDD-FI-04"), ev(ref="KDD-SD-12")], 0.85),
    ]


def sentinel(p: dict) -> list[dict]:
    return [item("sentinel_flag", "FLG-DSN-012 Daily dunning vs shipping without credit review", {
        "id": "FLG-DSN-012", "kind": "conflict", "area_affected": "Finance and Sales & Distribution",
        "why": "Parallel tracks assume opposite handling of credit-blocked orders during dunning runs.",
        "risk_if_ignored": "Credit-blocked orders ship while the dunning run chases the same customer.",
        "suggested_action": "Schedule mandatory joint alignment session between FI-AR Lead and SD Lead before the Design Readiness Gate.",
        "decision_ids": ["KDD-FI-04", "KDD-SD-12"], "track_a": "Finance (Automated daily dunning execution)",
        "track_b": "Sales & Distribution (Automated shipping without manual credit review)", "suggested_attendee": "FI-AR Lead and SD Lead"},
        [ev(D.DQ["CONF_FI"], "Sofia", "00:05:20"), ev(D.DQ["CONF_SD"], "Dev", "00:30:00")], 0.92)]


# ---------------------------------------------------------------------------------------------- Phase 3

def fs_review(p: dict) -> list[dict]:
    return [item("fs_gap_report", "FS coverage review: Z_DUNNING_EXT", {
        "id": "FSGAP-01",
        "coverage_matrix": [
            {"requirement_id": "REQ-SD-042", "fs_section": "Section 4.1 (Credit Rules)", "status": "Partial",
             "gaps": "Missing authorization object checks (F_KNA1_BED) for override exceptions.", "acceptance_criteria": "Yes"},
            {"requirement_id": "REQ-SD-042", "fs_section": "Section 4.3 (Audit Log)", "status": "Missing",
             "gaps": "No logging mechanism specified for suppressed dunning notices.", "acceptance_criteria": "No"},
            {"requirement_id": "REQ-FI-019", "fs_section": "Not Present", "status": "Unmapped (Missed)",
             "gaps": "Requirement was rejected at CP1 in Prepare and never reached the FS.", "acceptance_criteria": "None"}],
        "gaps": [
            {"type": "functional", "detail": "Missing authorization object checks (F_KNA1_BED) for override exceptions.", "severity": "Major"},
            {"type": "non_functional", "detail": "No audit logging specified for suppressed dunning notices.", "severity": "Major"},
            {"type": "traceability", "detail": "REQ-FI-019 exists in the Prepare ledger as rejected; confirm it is intentionally out of scope.", "severity": "Blocker"}]},
        [ev(ref="FS 4.1"), ev(ref="FS 4.3"), ev(ref="rejection:REQ-FI-019")], 0.9)]


def review(p: dict) -> list[dict]:
    mode = p.get("review_mode")
    if mode == "fs":
        return [
            item("review_finding", "REV-01 FS lacks role definition for dunning suppression", {
                "id": "REV-01", "severity": "Blocker", "rule_id": "FS-RULE-04", "location": "FS Section 4.2", "mode": "fs",
                "snippet": "Section 4.2 lacks user role definition for dunning suppression.",
                "suggested_fix": "Add explicit role mapping table (Z_AR_MANAGER) to restrict override rights."},
                 [ev(D.FS_Q["REV01"], ref="FS 4.2")], 0.95),
            item("review_verdict", "FS review verdict: Fail", {"id": "RV-FS", "verdict": "Fail", "blockers": 1, "majors": 0, "minors": 0,
                                                               "summary": "Blocker: missing role definition."}, [ev(ref="REV-01")], 0.9)]
    return [
        item("review_finding", "REV-02 SELECT inside loop in Z_DUNNING_EXT", {
            "id": "REV-02", "severity": "Major", "rule_id": "CODE-RULE-12", "location": "include Z_DUNNING_EXT", "mode": "code",
            "snippet": "SELECT statement inside loop in include Z_DUNNING_EXT.",
            "suggested_fix": "Replace loop selection with a buffered internal table lookup or join."},
             [ev(D.ABAP_Q["REV02"], ref="Z_DUNNING_EXT")], 0.95),
        item("review_finding", "REV-03 Hardcoded currency conversion factor", {
            "id": "REV-03", "severity": "Critical", "rule_id": "CODE-RULE-05", "location": "include Z_DUNNING_EXT", "mode": "code",
            "snippet": "Hardcoded currency conversion factors used instead of dynamic market data tables, compounding the missed multi-currency requirement (REQ-FI-019).",
            "suggested_fix": "Replace hardcoded multipliers with standard exchange rate API calls."},
             [ev(D.ABAP_Q["REV03"], ref="Z_DUNNING_EXT")], 0.96),
        item("review_verdict", "Code review verdict: Fail", {"id": "RV-CODE", "verdict": "Fail", "blockers": 0, "majors": 1, "minors": 0,
                                                             "summary": "Critical hardcoded conversion plus SELECT in loop."}, [ev(ref="REV-02"), ev(ref="REV-03")], 0.9)]


def test_gen(p: dict) -> list[dict]:
    return [
        item("unit_test_case", "TC-SD-01 Credit block, notice suppressed (positive)", {
            "id": "TC-SD-01", "requirement_ids": ["REQ-SD-042"], "category": "positive",
            "steps": "Order placed, credit block triggered, dunning run executed", "expected": "Notice suppressed"}, [ev(ref="REQ-SD-042 / FS 4.1")], 0.9),
        item("unit_test_case", "TC-SD-02 No credit block, notice sent normally (negative)", {
            "id": "TC-SD-02", "requirement_ids": ["REQ-SD-042"], "category": "negative",
            "steps": "Order placed, no credit block, dunning run executed", "expected": "Notice sent normally"}, [ev(ref="REQ-SD-042 / FS 4.1")], 0.9),
        item("coverage_gap", "TC-SD-03 Missing authorization test", {
            "id": "TC-SD-03", "type": "missing_negative_or_authorization_test", "ref": "REQ-SD-042",
            "detail": "Unauthorized user attempts to override credit dunning block. No test case exists (fails Definition of Done)."},
             [ev(ref="REQ-SD-042 / FS 4.2")], 0.88)]


# ---------------------------------------------------------------------------------------------- Phase 4

def dep_sequencer(p: dict) -> list[dict]:
    return [
        item("test_dependency", "TC-SD-02 depends on TC-SD-01", {
            "test_id": "TC-SD-02", "predecessor_id": "TC-SD-01", "type": "sequence", "what_needed": "Credit-blocked order from TC-SD-01",
            "provided_by": "tester TC-SD-01", "needed_by": "TC-SD-02 start", "risk_if_missing": "Cannot create the comparison order", "documented": True},
             [ev(ref="TC-SD-01"), ev(ref="TC-SD-02")], 0.9),
        item("blocker_risk", "Unauthorized-user test needs a restricted test user", {
            "id": "BR-1", "test_id": "TC-SD-03", "what_needed": "Test user without Z_AR_MANAGER role", "provided_by": "Security team",
            "risk_if_missing": "TC-SD-03 cannot run; authorization gap stays untested"}, [ev(ref="TC-SD-03")], 0.7, True)]


# ---------------------------------------------------------------------------------------------- Phase 5

def observations(p: dict) -> list[dict]:
    r = p.get("rehearsal_id", "DR1")
    return [
        item("observation", "TSK-FI-088 started 90 minutes late", {
            "id": "OBS-01", "rehearsal_id": r, "task_id": "TSK-FI-088", "classification": "problem", "category": "sequencing_dependencies",
            "what_happened": "Customer master load started 90 minutes late because of an unsequenced customer master dependency.",
            "impact": "Critical path extended", "suggested_follow_up": "Add a prerequisite validation check before TSK-FI-088"},
             [ev(D.NOTE_Q["O88"], "Data Migration Lead", "03:45:12")], 0.95),
        item("observation", "TSK-FI-112 failed reconciliation (INR 1,420,000)", {
            "id": "OBS-02", "rehearsal_id": r, "task_id": "TSK-FI-112", "classification": "problem", "category": "data_quality_migration",
            "what_happened": "Multi-currency invoice reconciliation failed with a variance of INR 1,420,000 (ERR-FIN-99); invoices were converted with fixed rates.",
            "impact": "Data integrity breach above tolerance", "suggested_follow_up": "Dynamic currency translation; re-inject REQ-FI-019"},
             [ev(D.NOTE_Q["O112"], "Financial Controller", "04:02:30")], 0.97),
        item("observation", "TSK-SD-104 completed on time", {
            "id": "OBS-03", "rehearsal_id": r, "task_id": "TSK-SD-104", "classification": "smooth", "category": "sequencing_dependencies",
            "what_happened": "Credit control area configuration completed in the planned 30 minutes.", "impact": "None",
            "suggested_follow_up": "Keep as the pattern for configuration tasks"},
             [ev(D.NOTE_Q["O104"], "SD Lead", "04:10:00")], 0.9)]


def refinement(p: dict) -> list[dict]:
    return [item("refinement_proposal", "Sequence customer master prerequisite and re-inject multi-currency requirement", {
        "observation": ("Task TSK-FI-088 started 90 minutes late due to an unsequenced customer master dependency. Furthermore, task TSK-FI-112 "
                        "failed reconciliation due to missed multi-currency conversion rules stemming from an early-stage requirement drop (REQ-FI-019)."),
        "evidence_summary": "Execution log timestamp 03:45:12, reconciliation variance error report ERR-FIN-99, and bridge-call escalation notes.",
        "root_cause": "REQ-FI-019 rejected at CP1 (unclear audio), never reached FS, tests or code; hardcoded conversion factors (REV-03).",
        "root_cause_confidence": "high",
        "proposed_change": ("1. Update runbook sequence: add pre-requisite validation check before TSK-FI-088. 2. Re-inject REQ-FI-019 into the scope "
                            "backlog, mandate dynamic currency translation logic in code review guidelines, and add test cases for multi-currency "
                            "rounding prior to Dry Run 2."),
        "target": "guideline", "change_type": "new_rule",
        "rule_text": "Code review: hardcoded currency conversion is a Blocker; multi-currency verification test is mandatory for any FI posting enhancement.",
        "reinstate_requirements": [{"id": "REQ-FI-019", "type": "requirement", "process_area": "FI-GL", "sub_process": "Tax / currency translation",
                                    "as_is": "Rounding rules for tax translation when posting in multiple currencies",
                                    "to_be": "Dynamic currency translation with defined rounding rules", "priority": "Must", "owner": "Ravi (GL Lead)"}],
        "expected_benefit": "Removes an idle wait on the critical path and the multi-currency reconciliation failure.",
        "risk_of_change": "Dry Run 2 scope grows by the multi-currency tests.", "affected": ["TSK-FI-088", "TSK-FI-112", "REV-03", "REQ-FI-019"]},
        [ev(ref="TSK-FI-088"), ev(ref="TSK-FI-112"), ev(ref="ERR-FIN-99")], 0.93)]


RESPONDERS = {
    "Workshop Prep Agent": workshop_prep,
    "Capture & Extraction Agent": capture,
    "Cross-Process Impact Agent": cross_process,
    "Design Scribe": scribe,
    "Cross-Functional Sentinel": sentinel,
    "FS Gap Analyzer and FS Starter": fs_review,
    "Review Agent (FS, TS, Code)": review,
    "Test Case (TUT) Generator and Coverage Checker": test_gen,
    "Dependency and Sequencer": dep_sequencer,
    "Observation Logger": observations,
    "Refinement Advisor Agent": refinement,
}


class DemoLLM:
    """Implements the LLMClient protocol with the dataset's recorded agent outputs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_json(self, *, system: str, user: str, schema: dict, max_tokens: int | None = None) -> LLMResult:
        m = re.search(r"SKILL: (.+)", system)
        title = m.group(1).strip() if m else ""
        self.calls.append(title)
        pm = re.search(r"EVENT PAYLOAD \(data\):\n(\{.*\})", user)
        payload: dict[str, Any] = json.loads(pm.group(1)) if pm else {}
        fn = RESPONDERS.get(title)
        items = fn(payload) if fn else []
        return LLMResult(data={"items": items, "open_questions": [], "notes": "scripted demo output"}, model="demo-script")
