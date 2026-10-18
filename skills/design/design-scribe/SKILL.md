---
name: design-scribe
agent_id: design.design_scribe
phase: design
title: Design Scribe
triggers:
- design.transcript.received
mode: llm
emits:
- design.extraction.completed
checkpoint: D-SCRIBE
approver_roles:
- workshop_lead
tier: 1
output_kinds:
- decision
- assumption
- risk
- dev_object
- action_item
- open_issue
- recap_draft
evidence_optional_kinds:
- recap_draft
source_field: transcript
postprocess:
- design_mandatory
context:
- requirement_entry
- decision
- workshop
---

Record a design session (<source>, payload workshop_id) into the Design Register. Emit items of these kinds, each linked to requirement ids:
- `decision`: {id (KDD-nn), description, rationale, alternatives, requirement_ids, workshop_id, impacted_tracks, owner, depends_on, external_party (bool), fit_gap (fit|gap) or brownfield_impact (simplification_item|custom_code|interface), status:"proposed"}
- `assumption`: {id, statement, owner, validation_due (ISO date if stated), critical (bool), decision_id}  (also risks as kind `risk`)
- `dev_object`: {id, name, type (config|workflow|report|interface|conversion|enhancement|form|authorization|fiori_ui|analytics), complexity (simple|medium|complex), requirement_ids, decision_ids, prerequisites, scope_status:"proposed"}
- `action_item`, `open_issue`
- `recap_draft`: one item {decisions, actions, open_items, request_to_confirm}. The workshop lead sends it; replies are evidence of agreement, never a sign-off.
Quotes must be verbatim with timestamp and speaker. Label stated vs inferred honestly; leave blank mandatory fields blank (owner, rationale, impacted_tracks): they are listed for the human. Never record a sign-off.
