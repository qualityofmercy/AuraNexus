# Runbook

## Environments

| Env | Terraform root | Notes |
|---|---|---|
| shared-services | `environments/shared-services` | VPC (shared), Artifact Registry `auranexus` (immutable tags) |
| dev | `environments/dev` | `protect_data=false`, single-zone DB, scale to zero |
| prod | `environments/prod` | `protect_data=true`, regional HA DB, min 1 instance, deletion protection |

Provider note: dev/prod use `hashicorp/google ~> 6.0` (Cloud Run `deletion_protection`); shared-services stays on `~> 5.0`.
CI rolls images with `gcloud run services update --image` (`cloudbuild.yaml`); Terraform ignores image drift.
For prod, deploy digest-pinned images from a protected branch/tag trigger (`_ENV=prod`).

## First deployment

```bash
scripts/bootstrap.sh <project> [org/repo]
(cd environments/shared-services && terraform init && terraform apply -var project_id=<project>)
gcloud builds submit --tag asia-south1-docker.pkg.dev/<project>/auranexus/auranexus:v0 .   # first image; later releases use cloudbuild.yaml
(cd environments/dev && cp terraform.tfvars.example terraform.tfvars && $EDITOR terraform.tfvars && terraform init && terraform apply)
gcloud run jobs execute auranexus-migrate-dev --region asia-south1 --wait
```

## Onboard a tenant, a PM and a project

Tenants are isolated by RLS; membership and roles live in the tenant's `members` table (not in tokens).
The first admin comes from Terraform: `tenants = { acme = { display_name = "...", admin_email = "pm@acme.com" } }`.
The migration job (`gcloud run jobs execute auranexus-migrate-<env> --wait`) registers every tenant and makes its
`admin_email` admin + PM (idempotent). That person then adds members and projects through the API:

```bash
API=https://auranexus-api-dev-<project-number>.asia-south1.run.app
T=$(gcloud auth print-identity-token)   # user login; for a service account add --audience=$API
H=(-H "Authorization: Bearer $T" -H "X-Auranexus-Token: $T" -H "X-Tenant-Id: acme" -H "content-type: application/json")
curl -X PUT  "$API/v1/members"  "${H[@]}" -d '{"email":"lead@acme.com","roles":["workshop_lead","functional_lead"]}'
curl -X POST "$API/v1/projects" "${H[@]}" -d '{"id":"prj1","name":"S/4 Greenfield","project_type":"greenfield"}'
```

**Why two token headers?** Cloud Run validates `Authorization` at the edge (IAM invoker) and then replaces the token's
signature, so the app cannot re-verify it. Clients therefore send the same token in `X-Auranexus-Token`, which arrives intact
and is fully verified (audience, signature, expiry) by the app; roles come from the tenant member table. Callers outside
Cloud Run may send only `Authorization`. `/healthz` is reserved by Cloud Run's front end externally (404): use `/readyz`.
For `dev`, `extra_oidc_audiences` accepts the gcloud CLI client id so a developer can use their own login; leave it empty in prod
and use a service account with `--audience=$API`.

The worker (Pub/Sub push, internal ingress, only invoker = Pub/Sub SA) sets `AURANEXUS_TRUST_EDGE_IAM=true`; the API sets
`AURANEXUS_ENABLE_INTERNAL=false` and has no `/internal/*` routes. Never enable edge trust on a service users can invoke.

Local mode (no GCP) uses dev headers instead of the token: `-H 'X-Tenant-Id: acme' -H 'X-Dev-User: pm@acme.com' -H 'X-Dev-Roles: pm'`
(`POST /v1/tenants?tenant_id=acme` with role `admin` creates a tenant locally).

Typical Prepare loop: `POST /v1/projects/prj1/records/workshop` (plan) → `POST .../events {"type":"workshop.scheduled",...}`
(briefing, CP0) → `POST .../events {"type":"transcript.received","payload":{"workshop_id","process_area","attendees","transcript"}}`
→ review `GET /v1/checkpoints` → `POST /v1/checkpoints/{id}/decision`.

## Operating

| Task | How |
|---|---|
| See what is waiting for humans | `GET /v1/checkpoints?project_id=` (overdue and escalation level included) |
| Failed or stuck events | Pub/Sub DLQ subscription `auranexus-<env>-events-dlq-pull`; inspect `GET /v1/projects/{id}/runs` (`status=failed`, `error`); fix the cause, re-submit the event with the same `id` (completed agents are skipped, failed ones re-run) |
| Verify audit integrity | `GET /v1/audit/verify` (pm/admin) |
| Re-freeze the cutover rubric | `POST /v1/projects/{id}/rubric/freeze` (pm). Required after editing `config/rubrics/cutover_scoring.yaml`; otherwise `run.scoring` fails with `RubricFrozenError` by design |
| Tune HITL deadlines/tiers | `config/hitl_policy.yaml` then redeploy |
| Add or change an agent | edit/add `skills/<phase>/<name>/SKILL.md`; `pytest tests/test_skills.py`; `python scripts/gen_agent_catalog.py` |
| Release a drafted notification | `POST /v1/notifications/{id}/release` |
| Notifications to Teams/Slack/email | consume subscription `auranexus-<env>-notifications-pull` with your connector (not included) |
| Rotate DB credentials | taint `random_password.app` (and `owner`), `terraform apply`; new secret versions are picked up on next revision (`gcloud run services update ... --update-env-vars=ROLLOUT=<ts>`) |
| Model / provider change | set `llm_backend` (`gemini` default, or `claude`) and `model` in the environment tfvars (`AURANEXUS_LLM_BACKEND`, `AURANEXUS_MODEL`); empty `model` uses the backend default (`gemini-2.5-pro`). Confirm the model id, region and quota in Vertex AI Model Garden first, then re-run the pilot comparison before switching prod |

## Guardrail checks before go-live (per environment)

1. `AURANEXUS_ENV=prod` boots (it refuses dev auth, memory store, or fake LLM).
2. API invokers are groups, never `allUsers`; worker ingress is internal-only.
3. Confirm Vertex AI access to the chosen Gemini model in your region/quotas and that your data-handling policy allows the
   transcripts you plan to send (client consent for recording/transcription is a precondition of the Prepare spec).
4. Run a pilot (Prepare spec: one process area, 2-3 workshops) and compare agent items against human-validated entries; the
   rejection rate and `quote_not_verified` rate are your extraction-quality signals (`hitl_decisions` in BigQuery).

## Known limitations

* The Postgres store and the Terraform stacks were validated statically (`pytest`, `terraform validate`); they have not been applied against a live GCP project or database in this repo's CI. The first `terraform apply` and migration run should be done in dev.
* The Docker image and `docker-compose.yml` are unbuilt in this environment (no Docker daemon); CI builds the image.
* Connectors (Teams/Zoom transcripts, Jira/SharePoint/Cloud ALM, Slack/Teams notifications) and ATC/abapGit ingestion are integration points, not implementations: see [phase-mapping.md](phase-mapping.md).
* Authorisation is role-based per tenant, not per project; every member sees every project of the tenant.
* Reuse search is lexical; add embeddings if the past-RICEFW library grows large.
* Large transcripts: input is capped (`AURANEXUS_MAX_INPUT_CHARS`, default 400k chars) and rejected rather than truncated. Split long sessions.
* LLM prompts have not been tuned against real client transcripts; treat the first pilot as the evaluation set.
