---
name: cross-process-impact
agent_id: prepare.cross_process_impact
phase: prepare
title: Cross-Process Impact Agent
triggers:
- extraction.completed
mode: llm
checkpoint: CP3
approver_roles:
- pm
tier: 1
output_kinds:
- cross_team_flag
tools:
- knowledge:interdependency_map
proposal_context:
- requirement_entry
context:
- cross_team_flag
---

Match every entry of this workshop (<register>.batch_proposals) against the Process Interdependency Map (<facts>.interdependency_map). Dependencies cover process, data, interface and organisational types.

Emit one item of kind `cross_team_flag` per (target area, reason) with payload: `id`, `source_workshop`, `requirement_ids`, `target_area`, `why` (the dependency and the specific statement that triggers it), `risk_if_not_discussed`, `suggested_action` (workshop or attendee), `suggested_attendee`, `dependency_type`. Group by target team: one flag can list several requirement_ids. Evidence = the triggering quote(s) from batch_proposals evidence plus source_ref of the map entry.
Example: Affects FI-AR because the credit block rule changes the dunning process; risk: dunning configuration built on wrong assumptions; action: add an FI-AR session with the Accounts Receivable lead.
Do not flag dependencies the statements do not actually touch. Never mark a flag raised or closed.
