#!/usr/bin/env bash
# One-time GCP bootstrap: enable APIs, create the Terraform state bucket and a least-privilege deployer
# service account. Idempotent: safe to re-run.
#
#   scripts/bootstrap.sh <project-id> [github-org/repo]
#
# Env overrides: REGION (asia-south1), STATE_BUCKET (auranexus-terraform-state-store)
set -euo pipefail

PROJECT_ID="${1:?usage: bootstrap.sh <project-id> [github-org/repo]}"
GITHUB_REPO="${2:-}"
REGION="${REGION:-asia-south1}"
STATE_BUCKET="${STATE_BUCKET:-auranexus-terraform-state-store}"
DEPLOYER="auranexus-terraform"
DEPLOYER_EMAIL="${DEPLOYER}@${PROJECT_ID}.iam.gserviceaccount.com"

command -v gcloud >/dev/null || { echo "gcloud CLI is required" >&2; exit 1; }
gcloud config set project "${PROJECT_ID}" >/dev/null

echo ">> enabling bootstrap APIs"
gcloud services enable \
  cloudresourcemanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
  storage.googleapis.com serviceusage.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

echo ">> state bucket gs://${STATE_BUCKET}"
if ! gcloud storage buckets describe "gs://${STATE_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${STATE_BUCKET}" \
    --location="${REGION}" --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning

echo ">> deployer service account ${DEPLOYER_EMAIL}"
gcloud iam service-accounts describe "${DEPLOYER_EMAIL}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${DEPLOYER}" --display-name="AuraNexus Terraform deployer"

ROLES=(
  roles/serviceusage.serviceUsageAdmin
  roles/compute.networkAdmin
  roles/servicenetworking.networksAdmin
  roles/cloudsql.admin
  roles/run.admin
  roles/pubsub.admin
  roles/cloudscheduler.admin
  roles/bigquery.admin
  roles/secretmanager.admin
  roles/cloudkms.admin
  roles/storage.admin
  roles/artifactregistry.admin
  roles/iam.serviceAccountAdmin
  roles/iam.serviceAccountUser
  roles/resourcemanager.projectIamAdmin
)
for r in "${ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER_EMAIL}" --role="${r}" --condition=None --quiet >/dev/null
done

if [[ -n "${GITHUB_REPO}" ]]; then
  echo ">> Workload Identity Federation for GitHub repo ${GITHUB_REPO}"
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
  gcloud iam workload-identity-pools describe github --location=global >/dev/null 2>&1 || \
    gcloud iam workload-identity-pools create github --location=global --display-name="GitHub"
  gcloud iam workload-identity-pools providers describe github-oidc --location=global \
    --workload-identity-pool=github >/dev/null 2>&1 || \
    gcloud iam workload-identity-pools providers create-oidc github-oidc --location=global \
      --workload-identity-pool=github --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
      --attribute-condition="assertion.repository=='${GITHUB_REPO}'"
  gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_EMAIL}" \
    --role=roles/iam.workloadIdentityUser \
    --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${GITHUB_REPO}" >/dev/null
  echo "   provider: projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-oidc"
fi

cat <<EOF

Bootstrap complete.
Next:
  1. cd environments/shared-services && terraform init && terraform apply -var project_id=${PROJECT_ID}
  2. Build and push the first image (Cloud Build: gcloud builds submit --config cloudbuild.yaml ...)
  3. Fill environments/dev/terraform.tfvars (from terraform.tfvars.example), then terraform init && apply
  4. Run the migration job: gcloud run jobs execute auranexus-migrate-dev --region ${REGION} --wait
  5. Register the first tenant and admin (docs/runbook.md)
EOF
