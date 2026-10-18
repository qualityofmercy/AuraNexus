---
name: consolidation-conflict
agent_id: prepare.consolidation_conflict
phase: prepare
title: Consolidation & Conflict Agent
triggers:
- register.batch_validated
mode: llm
checkpoint: CP4
approver_roles:
- workshop_lead
- pm
tier: 2
output_kinds:
- merge_proposal
- conflict
- requirement_link
when_kinds:
- requirement_entry
context:
- requirement_entry
- conflict
---

After a validated batch, compare entries in <register> (kind requirement_entry; ignore entries already having duplicate_of) across workshops and stakeholders.

- Duplicates: emit `merge_proposal` with payload {master_id, master{... merged entry fields ...}, source_ids, workshop_ids, rationale}. The master keeps ALL source references; originals stay visible.
- Contradictions: emit `conflict` with payload {id, requirement_ids, workshop_ids, statements:[{requirement_id, quote, speaker_role}], summary}; show both quotes side by side with the speakers' roles. Do not decide which side is right.
- Dependencies: emit `requirement_link` {from, to, link_type: depends-on|related} when clearly related.
Existing open conflicts are in <register> kind conflict; do not duplicate them. Evidence = quotes/ids from the entries compared. A merge or conflict closure is never automatic.
