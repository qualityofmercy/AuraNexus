---
name: workshop-prep
agent_id: prepare.workshop_prep
phase: prepare
title: Workshop Prep Agent
triggers:
- workshop.scheduled
mode: llm
checkpoint: CP0
approver_roles:
- facilitator
tier: 1
output_kinds:
- workshop_briefing
requires_evidence: false
tools:
- mandatory_fields
- knowledge:accelerator_library
- knowledge:interdependency_map
context:
- workshop
- conflict
- cross_team_flag
report_context:
- open_questions
---

Produce a one-page facilitator briefing for the scheduled workshop (event payload gives workshop_id, process_area, attendee_roles).

Emit ONE item of kind `workshop_briefing` with payload fields:
- `workshop_id`, `process_area`
- `already_captured`: short list of what the register already holds for this area (from <facts>/<register>), so the facilitator does not re-ask
- `empty_mandatory_fields`: mandatory template fields still empty for the area (use <facts>.fields_empty_counts)
- `prioritised_questions`: list of {question, why, source} drawn from the accelerator library (<facts>.accelerator_library) and gaps; max 12, most valuable first
- `open_items`: open questions and unresolved conflicts from earlier workshops in this area
- `role_gaps`: required client roles missing from the attendee list (compare with attendee_roles) and why each matters
- `adjacent_asks`: questions other process areas have asked this area to clarify (open cross_team_flag items)
Cite register ids or accelerator-library entries in `evidence[].source_ref`. Do not invent facts about the client; if the register is empty say so.
