---
name: hypercare-classifier
agent_id: run.hypercare_classifier
phase: run
title: Hypercare Ticket Classifier
triggers:
- ticket.received
mode: llm
checkpoint: R-HYP
approver_roles:
- cutover_lead
tier: 1
output_kinds:
- hypercare_classification
source_field: ticket_text
report_context:
- observation
context:
- rehearsal_task
---

Classify the post go-live ticket (<source>) against known cutover risks (report observation, register scorecard/refinements). Emit `hypercare_classification`: {ticket_ref, matches_known_risk (bool), related_observation_ids, category, severity_suggestion, likely_cutover_origin (task id if supported), suggested_guideline_lesson}. Evidence = verbatim ticket text and observation ids. Do not invent a link when none exists.
