#!/usr/bin/env bash
# ==============================================================================
# CleanNotes PrintFlow POS (B2B Server) — Cloud Run Deployment Automation
# Self-contained within apps/shopkeeper-web/deploy/
# Targets GCP Mumbai Region (asia-south1) for lowest latency across Indian Xerox shops
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

PROJECT_ID="${GCP_PROJECT_ID:-cleannotes-prod}"
REGION="${GCP_REGION:-asia-south1}"
SERVICE_NAME="cleannotes-b2b-pos"
IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"

echo "=== [1/4] Pre-flight GCP Configuration Check ==="
echo "Working Directory: ${APP_DIR}"
echo "Project ID:        ${PROJECT_ID}"
echo "Region:            ${REGION} (Mumbai)"
echo "Service:           ${SERVICE_NAME}"

echo "=== [2/4] Building Self-Contained Container Image ==="
docker build -f "${SCRIPT_DIR}/Dockerfile" -t "${IMAGE_TAG}" "${APP_DIR}"

echo "=== [3/4] Pushing Container Image to Registry ==="
docker push "${IMAGE_TAG}"

echo "=== [4/4] Deploying to Cloud Run (Managed, High Availability) ==="
gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_TAG}" \
    --platform=managed \
    --region="${REGION}" \
    --allow-unauthenticated \
    --port=8001 \
    --min-instances=1 \
    --max-instances=10 \
    --cpu=2 \
    --memory=1Gi \
    --timeout=60s \
    --concurrency=8 \
    --set-env-vars="DOCUMORPH_ENV=production,ALLOWED_ORIGINS=https://cleannotes.app,https://cleannotes-pos.vercel.app" \
    --set-secrets="DOCUMORPH_B2B_SECRET=documorph-b2b-secret:latest,RAZORPAY_WEBHOOK_SECRET=razorpay-webhook-secret:latest"

echo "=== Verifying Production Health Probe ==="
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --platform=managed --region="${REGION}" --format="value(status.url)")
curl -f "${SERVICE_URL}/api/health"
echo ""
echo "=== CleanNotes PrintFlow POS successfully deployed to: ${SERVICE_URL} ==="
