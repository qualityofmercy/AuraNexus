# AuraNexus

AI-powered **project lifecycle management engine** for SAP Greenfield and Brownfield programmes, built on GCP.
It turns the five phase specifications (Prepare, Design, Build, Test, Run) into one multi-agent system with a
shared register, and **every decision stays with a human**.

> Agents draft, assess and flag. Humans decide. No agent records a sign-off, freezes scope, commits an estimate,
> merges records, changes a template or guideline, or applies a cutover-plan change on its own.

## What it does

| Phase | Agents | Headline capabilities |
|---|---|---|
| **Prepare** (6) | Workshop Prep, Capture & Extraction, Template Steward, Cross-Process Impact, Consolidation & Conflict, Monitor & Quality | Transcript → evidence-backed requirement register; cross-team flags; duplicate/contradiction detection; workshop quality score and re-baseline triggers |
| **Design** (7) | Workshop Planner, Design Scribe, Cross-Functional Sentinel, Monitor & Readiness Gates, Scope Coverage Assessor, Skills & Estimation, Build Sequencer | Coverage/consistency/sign-off tracking; design-readiness and scope-freeze gates; ranked scope gaps; range estimates with basis; build waves and critical path |
| **Build** (9) | Requirement Intake, FS, TS Designer, Review, Test-Case Generator, Quality Monitor, Cutover Agent, DoD Gate, Change Impact | Requirement → FS → TS → code → test → cutover traceability chain; Definition-of-Done gate; governed rule library (two approvers) |
| **Test** (5) | TestStarter, Dependency & Sequencer, Coverage & Readiness Assessor, Handoff Orchestrator, Cutover Plan Sync | Tracker workbook (`.xlsx`); waves and blockers; mid/end-phase assessments; automatic tester handoffs and nudges; test-driven cutover plan proposals |
| **Run** (7) | Cutover Planner, Execution Monitor, Observation Logger, Scoring, Refinement Advisor, Executive Summary, Hypercare Classifier | Live planned-vs-actual; frozen-rubric rehearsal scoring (Green/Amber/Red with overrides); tiered refinement proposals; retrospective with measured AI value |

34 agents in total, each defined by one `skills/<phase>/<name>/SKILL.md` ([catalog](docs/agents.md)).
The HITL Gatekeeper and Guideline Steward from the Run spec are implemented as workflow
(`core/hitl.py`, `core/appliers.py`) rather than agents, as that spec recommends.

## Architecture in one picture

```
 transcripts / human records / schedule ticks
                  │
        ┌─────────▼─────────┐        Pub/Sub (events, DLQ)         ┌──────────────────────┐
        │  API (Cloud Run)  │──────────────────────────────────────▶  Worker (Cloud Run)  │
        │ HITL, ingest, read│                                       │ Orchestrator → Agents │
        └─────────┬─────────┘                                       └───┬──────────────┬───┘
                  │ decide                                              │ LLM          │ deterministic
                  │                                                     ▼              ▼ tools (graphs,
        ┌─────────▼──────────┐   proposals + checkpoints        Gemini on Vertex AI     scoring, gates)
        │   HITL service     │◀───────────────────────────────────────────┘
        │ roles · tiers · SoD│── approved only ──▶ Appliers ──▶ Register (Cloud SQL, RLS per tenant)
        └─────────┬──────────┘                                  Audit log (hash-chained, append-only)
                  └─▶ BigQuery (PM dashboards, HITL latency, scores)   GCS (CMEK) for files
```

Key design choices (details in [docs/architecture.md](docs/architecture.md)):

* **LLMs interpret, code computes (provider-agnostic: Gemini or Claude on Vertex AI).** Scores, weights, critical paths, waves, coverage and gates are deterministic Python
  (`src/auranexus/tools`), unit-tested. The model never does arithmetic that a human will rely on.
* **Guardrails enforced in code, not prompts** (`core/guardrails.py`): no item without evidence, quotes verified against
  the source text (unverifiable quotes are downgraded to *inferred*, confidence-capped and flagged), whitelisted output
  kinds per agent, estimates must be ranges with a basis, urgency never attaches to a person.
* **One gate to the register.** Agents write *proposals*; only `HITLService.decide()` → appliers can write decided state.
  Roles, separation of duties, required reasons, multi-approver tier-3 changes, deadlines and escalation are policy
  ([`config/hitl_policy.yaml`](config/hitl_policy.yaml)).
* **Multi-tenant by construction**: `tenant_id` on every row + PostgreSQL row-level security with a non-owner,
  `NOBYPASSRLS` app role; per-tenant GCS prefixes; per-tenant audit chain.
* **Auditability**: every agent run, proposal, decision and escalation lands in a SHA-256 hash-chained audit log
  (`GET /v1/audit/verify`), backed by an append-only trigger.

## Guided demo

A browser walkthrough of all five phases on a synthetic dataset, with persona switching and role-enforced approvals:
[docs/demo.md](docs/demo.md). Run locally with `uvicorn auranexus.demo.app:create_app --factory --port 8099`, or deploy the
isolated sandbox with `scripts/deploy_demo.sh`.

## Quick start (local, no GCP)

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q                                           # 73 tests
python scripts/demo.py                              # Prepare flow end to end with a scripted LLM

AURANEXUS_ENV=local uvicorn auranexus.api.app:create_app --factory --port 8080
# dev auth: send X-Tenant-Id / X-Dev-User / X-Dev-Roles headers (see docs/runbook.md)
```

Prod-like locally (Postgres with RLS): `docker compose up --build`.

Real LLM locally: `pip install -e ".[gcp]"`, `gcloud auth application-default login`, then
`AURANEXUS_LLM_BACKEND=gemini AURANEXUS_GCP_PROJECT=<proj>` (see [.env.example](.env.example)). Gemini on Vertex AI is the default
GCP backend; Claude on Vertex AI is available with `llm_backend=claude` (`pip install -e ".[claude]"`).

## Deploy to GCP

1. `scripts/bootstrap.sh <project-id> [org/repo]`: APIs, Terraform state bucket, deployer SA (+ optional GitHub WIF).
2. `environments/shared-services`: shared VPC and Artifact Registry. `terraform apply`.
3. Build and push the image (`cloudbuild.yaml`).
4. `environments/dev` (then `prod`): copy `terraform.tfvars.example` → `terraform.tfvars`, `terraform apply`.
5. Run the migration job, register the first tenant. See [docs/runbook.md](docs/runbook.md).

Each environment is one instantiation of [`modules/auranexus-env`](modules/auranexus-env/main.tf)
(networking, IAM, KMS+GCS, Cloud SQL private IP, Pub/Sub + DLQ + Scheduler, BigQuery, Cloud Run api/worker/migrate job),
so dev and prod differ only by inputs.

## Repository layout

```
src/auranexus/
  domain/        models: Proposal, Checkpoint, Decision, Event, Evidence, roles, phases
  core/          store (memory | Postgres+RLS), repo + audit chain, HITL, appliers, guardrails, LLM (Vertex), bus (Pub/Sub), analytics
  agents/        SKILL.md loader, registry, AgentRunner (prompt → LLM → guardrails → proposals)
  tools/         deterministic tools per phase (graph, scoring, gates, handoff, coverage, ...)
  orchestrator/  event router (not a reasoning agent), checkpoint tracking, schedule fan-out, escalation
  api/           FastAPI app, OIDC auth, role checks, Pub/Sub push endpoint
  exports/       Excel tracker workbook
skills/          34 SKILL.md agent definitions (frontmatter = wiring, body = instructions)
config/          HITL policy, scoring rubrics, requirement template, interdependency map, accelerator library, profiles
migrations/      Postgres schema, RLS, append-only audit trigger
modules/ environments/   Terraform (GCP)
tests/ scripts/ docs/
```

## Source specifications

The design follows the five phase briefs (Prepare, Design, Build, Test, Run). How each requirement maps to code is in
[docs/phase-mapping.md](docs/phase-mapping.md); known gaps and next steps are listed in [docs/runbook.md](docs/runbook.md#known-limitations).
