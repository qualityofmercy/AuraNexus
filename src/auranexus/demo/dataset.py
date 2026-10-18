"""Synthetic demo dataset (Brownfield S/4HANA conversion, "Acme Industries").

One defect threads through all five phases: REQ-FI-019 (multi-currency tax translation rounding) is lost at CP1
(garbled audio, rejected by a human), approved around in Design (KDD-FI-09), unmapped in the FS, flagged but deferred in
code review (REV-03 hardcoded conversion), has no test (TC-FI-09), and finally fails the dry run (TSK-FI-112,
INR 1,420,000 discrepancy). Every evidence quote below is a verbatim substring of its source text.
"""

TENANT = "acme"
PROJECT = "demo-s4"
PROJECT_NAME = "Acme S/4HANA System Conversion (Demo)"

# ------------------------------------------------------------------------------------------------ Phase 1
WORKSHOP_ID = "W-FI-01"

PREP_TRANSCRIPT = """[00:02:10] Priya (Credit Manager): When an order is on credit block review, customers still get dunning letters and they call us upset. We need to suppress dunning notices while a credit block review is active to prevent customer friction.
[00:09:45] Marco (Procurement Lead): For purchase orders under ten thousand dollars we still do manual three-way matching, and it is the main reason invoices pile up at month end.
[00:13:05] Marco (Procurement Lead): One more thing, the material master weight unit differs between our plants, and cross-border stock transfers need it to be consistent for customs.
[00:17:30] Anita (AR Lead): Our legacy dunning rules and the custom exemption lists must be retained during the system conversion, there is no option to drop them.
[00:25:50] Priya (Credit Manager): Some key customers have special rebate agreements that are tied to their credit limits, we have to keep that working.
[00:41:12] Ravi (GL Lead): [crosstalk] ...tax translation... rounding when we post in multiple... [inaudible] ...minor currency differences, we have rules for that today."""

Q = {
    "SD042": "suppress dunning notices while a credit block review is active to prevent customer friction",
    "MM015": "manual three-way matching, and it is the main reason invoices pile up at month end",
    "FI008": "legacy dunning rules and the custom exemption lists must be retained during the system conversion",
    "FI019": "tax translation... rounding when we post in multiple",
    "FLG01a": "customers still get dunning letters",
    "FLG01b": "legacy dunning rules and the custom exemption lists",
    "FLG02": "material master weight unit differs between our plants",
    "FLG03": "special rebate agreements that are tied to their credit limits",
}

# ------------------------------------------------------------------------------------------------ Phase 2
DESIGN_TRANSCRIPT = """[00:05:20] Sofia (FI Lead): We decided to implement automated daily dunning execution via the standard S/4 job, it reduces manual accounting effort and accelerates cash collection.
[00:12:40] Dev (SD Lead): Sales representatives will not manually lift credit blocks in the UI. We rely on batch release rules to streamline the order fulfilment workflow.
[00:21:15] Sofia (FI Lead): For currency we use the standard exchange rate translation. I'm assuming zero minor-currency discrepancies, so no rounding logic, it simplifies the technical build scope.
[00:30:00] Dev (SD Lead): For shipping we will automate shipping without a manual credit review step."""

DQ = {
    "KDD04": "implement automated daily dunning execution via the standard S/4 job",
    "KDD12": "Sales representatives will not manually lift credit blocks in the UI",
    "KDD09": "use the standard exchange rate translation",
    "A01": "assuming zero minor-currency discrepancies",
    "CONF_FI": "automated daily dunning execution",
    "CONF_SD": "automate shipping without a manual credit review step",
}

# ------------------------------------------------------------------------------------------------ Phase 3
FS_TEXT = """Functional Specification: Dunning suppression during credit block review (Z_DUNNING_EXT)
4.1 Credit Rules: Dunning notices are suppressed for customers with an active credit block review. Override exceptions are allowed.
4.2 Roles: [no user role definition provided for dunning suppression]
4.3 Audit Log: [not specified]
Acceptance: suppressed customers receive no dunning notice during the review window."""

FS_Q = {"REV01": "no user role definition provided for dunning suppression"}

ABAP_TEXT = """INCLUDE z_dunning_ext.
LOOP AT lt_customers INTO ls_customer.
  SELECT SINGLE * FROM knkk INTO ls_knkk WHERE kunnr = ls_customer-kunnr.
  IF ls_knkk-crblb = 'X'.
    CONTINUE.
  ENDIF.
ENDLOOP.
lv_rate = '1.0845'.
lv_amount_local = lv_amount_doc * lv_rate."""

ABAP_Q = {
    "REV02": "SELECT SINGLE * FROM knkk INTO ls_knkk WHERE kunnr = ls_customer-kunnr",
    "REV03": "lv_rate = '1.0845'",
}

# ------------------------------------------------------------------------------------------------ Phase 4
TEST_SCRIPTS = [
    {"test_id": "TC-SD-01", "scenario": "Credit block dunning", "process_area": "SD", "scope_item": "Dunning suppression",
     "requirement_ids": ["REQ-SD-042"], "step_owner": "anna.sharma", "role": "tester", "category": "positive",
     "predecessor_ids": [], "planned_start": "{-5h}", "planned_end": "{-4h}"},
    {"test_id": "TC-SD-02", "scenario": "Credit block dunning", "process_area": "SD", "scope_item": "Dunning suppression",
     "requirement_ids": ["REQ-SD-042"], "step_owner": "ben.rao", "role": "tester", "category": "negative",
     "predecessor_ids": ["TC-SD-01"], "planned_start": "{-4h}", "planned_end": "{-3h}"},
    {"test_id": "TC-SD-03", "scenario": "Credit block dunning", "process_area": "SD", "scope_item": "Dunning suppression",
     "requirement_ids": ["REQ-SD-042"], "step_owner": "carol.iyer", "role": "tester", "category": "authorization",
     "predecessor_ids": ["TC-SD-02"], "planned_start": "{-3h}", "planned_end": "{-2h}"},
]

# ------------------------------------------------------------------------------------------------ Phase 5
NOTES = """[02:15:00] Cutover Manager: Dry Run 1 started. Customer master load TSK-FI-088 has not started, it is waiting on a customer master dependency nobody sequenced in the runbook.
[03:45:12] Data Migration Lead: TSK-FI-088 finally started, 90 minutes late. The customer master dependency was not in the runbook.
[04:02:30] Financial Controller: TSK-FI-112 reconciliation failed with a variance of INR 1,420,000, see error report ERR-FIN-99.
[04:10:00] SD Lead: TSK-SD-104 credit control configuration completed on time, no issues.
[04:15:00] Cutover Manager: Escalating TSK-FI-112 on the bridge. The multi-currency invoices were converted with fixed rates in the code."""

NOTE_Q = {
    "O88": "TSK-FI-088 finally started, 90 minutes late",
    "O112": "TSK-FI-112 reconciliation failed with a variance of INR 1,420,000",
    "O104": "TSK-SD-104 credit control configuration completed on time, no issues",
}

# Where the demo's trace thread starts
THREAD_REQ = "REQ-FI-019"
