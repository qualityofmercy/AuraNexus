# Human-in-the-loop

Every agent output that could change project state becomes a **Proposal** with an **open Checkpoint**. The register only
changes when an authorised human decides.

## Decisions

| Outcome | Effect | Reason required |
|---|---|---|
| `approve` | Counts as one vote; when `required_approvals` is reached the applier writes the artifact | no |
| `modify` | Approve with an edited payload (`modified_payload`); the edited version is what gets applied | yes |
| `reject` | Veto. Proposal rejected, a `rejection` record is stored (learning data; Template Steward watches patterns). Cross-team flags become *dismissed with reason* | yes |
| `defer` | Checkpoint stays open, deadline pushed out (`defer_hours`) | yes |

Rules (`core/hitl.py`, tested in `tests/test_hitl.py`):

* Only users holding one of the checkpoint's approver roles can decide; `viewer` and `admin` can never decide (separation of duties).
* Tier 3 needs two **distinct people holding distinct roles** (`pm`, `functional_lead`, `technical_lead` are added to the checkpoint).
* A user cannot approve the same checkpoint twice; concurrent decisions are serialised (optimistic `rev`).
* If the applier fails (e.g. closing a conflict without owner and resolution) the checkpoint is re-opened.
* Overdue checkpoints escalate (hourly sweep): level 1 adds `pm`, level 2 adds `steering`; `hitl.escalated` events are emitted.
* When the last checkpoint of a source event is decided, `register.batch_validated` is emitted (drives Consolidation).

## Policy (`config/hitl_policy.yaml`)

| Tier | Meaning | Deadline | Approvals |
|---|---|---|---|
| 1 | wording, single-record confirmation, minor tweaks | 48 h | 1 |
| 2 | sequence/dependency/owner changes, merges, template and plan changes, gates | 24 h | 1 |
| 3 | rollback, data-migration approach, business sign-off, guideline-library changes | 24 h | 2 distinct roles |

Run-phase refinement proposals get their tier computed deterministically from the change text (`refinement_post`); Build
guideline changes are always tier 3.

## Checkpoint map

| Code | Phase | Decision | Roles |
|---|---|---|---|
| CP0 | Prepare | Pre-workshop briefing | facilitator |
| CP1 | Prepare | Extracted entries | workshop_lead |
| CP2 | Prepare | Template change | pm, solution_architect |
| CP3 | Prepare | Cross-team flag (raise/dismiss) | pm |
| CP4 | Prepare | Duplicates and conflicts | workshop_lead, pm |
| CP5 / CP6 | Prepare | Weekly summary / re-baseline | pm |
| D-PLAN, D-SCRIBE, D-SENT, D-GATE, D-SCOPE, D-EST, D-SEQ | Design | plan, register entries, flags, gates, scope gaps, estimates, build plan | pm, workshop_lead, technical_lead, solution_architect, delivery_lead |
| B-REQ, B-FS, B-TS, B-REV, B-TUT, B-QM, B-CUT, B-DOD | Build | requirements, specs, reviews, tests, rule changes, cutover tasks, DoD | functional_lead, technical_lead, pm, cutover_lead |
| T-TRK, T-DEP, T-ASM, T-OPS, T-CUT | Test | tracker, dependencies, assessments, resequencing/escalation, cutover plan updates | test_lead, pm, cutover_manager |
| R-PLAN, R-SCORE, R-REF, R-RETRO, R-HYP | Run | plan, scorecard, refinements, retrospective, hypercare classification | cutover_manager, cutover_lead, pm |

## What needs no checkpoint, and why

Only three agents run without one: the **Observation Logger** (records findings with evidence; findings are not decisions),
the **Execution Monitor** (read-only), and **Change Impact** (a report). Auto-sent notifications are limited to tester
handoffs/nudges and critical-path alerts (`auto_send: true`); anything else an agent drafts stays `drafted` until a human
releases it (`POST /v1/notifications/{id}/release`). Sign-offs and other human-authored facts are written through
`POST /v1/projects/{id}/records/{kind}` with role checks and audit, never by agents.
