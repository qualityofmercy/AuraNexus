#!/usr/bin/env bash
# Deploy the sandbox demo (guided UI + scripted agents) as its own Cloud Run service.
#
#   scripts/deploy_demo.sh <project-id> <invoker-member> [region]
#   e.g. scripts/deploy_demo.sh my-project user:me@example.com asia-south1
#
# The demo service is isolated from dev/prod: in-memory data (AURANEXUS demo_mode refuses anything else), the scripted
# LLM, no VPC, no database, and a service account with ZERO roles. Exactly one instance, because state is in memory.
# Access is IAM-only. Browse it with:   gcloud run services proxy auranexus-demo --region <region> --project <project>
set -euo pipefail

PROJECT="${1:?usage: deploy_demo.sh <project-id> <invoker-member> [region]}"
INVOKER="${2:?invoker member, e.g. user:me@example.com or group:team@example.com}"
REGION="${3:-asia-south1}"
SERVICE="auranexus-demo"
SA="auranexus-demo-sa"
SA_EMAIL="${SA}@${PROJECT}.iam.gserviceaccount.com"
REPO="${REGION}-docker.pkg.dev/${PROJECT}/auranexus/auranexus"
TAG="demo$(date +%Y%m%d%H%M)"

cd "$(dirname "$0")/.."

echo ">> building ${REPO}:${TAG}"
gcloud builds submit . --project="${PROJECT}" --region="${REGION}" --tag="${REPO}:${TAG}" --quiet

echo ">> service account with no roles: ${SA_EMAIL}"
gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${SA}" --project="${PROJECT}" --display-name="AuraNexus demo sandbox (no permissions)"

echo ">> deploying ${SERVICE}"
gcloud run deploy "${SERVICE}" --project="${PROJECT}" --region="${REGION}" \
  --image="${REPO}:${TAG}" \
  --service-account="${SA_EMAIL}" \
  --command=python --args=-m,uvicorn,auranexus.demo.app:create_app,--factory,--host,0.0.0.0,--port,8080 \
  --min-instances=1 --max-instances=1 --concurrency=20 --cpu=1 --memory=512Mi --timeout=300 \
  --set-env-vars=AURANEXUS_ENV=dev \
  --no-allow-unauthenticated --quiet

gcloud run services add-iam-policy-binding "${SERVICE}" --project="${PROJECT}" --region="${REGION}" \
  --member="${INVOKER}" --role=roles/run.invoker --quiet >/dev/null

URL="$(gcloud run services describe "${SERVICE}" --project="${PROJECT}" --region="${REGION}" --format='value(status.url)')"
cat <<EOF

Demo deployed: ${URL}
Open it in a browser through an authenticated local proxy:
  gcloud run services proxy ${SERVICE} --region ${REGION} --project ${PROJECT} --port 8080
  then browse http://localhost:8080/

To share a public link instead (sandbox only: in-memory data, scripted LLM, no GCP permissions):
  gcloud run services add-iam-policy-binding ${SERVICE} --region ${REGION} --project ${PROJECT} --member=allUsers --role=roles/run.invoker
EOF
