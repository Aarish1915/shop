#!/usr/bin/env bash
# ==============================================================================
# CleanNotes PrintFlow POS — Custom Domain & SSL/TLS Mapping Automation
# Maps pos.cleannotes.app to Google Cloud Run service with automated managed certificates
# ==============================================================================

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-cleannotes-prod}"
REGION="${GCP_REGION:-asia-south1}"
SERVICE_NAME="cleannotes-b2b-pos"
DOMAIN="${1:-pos.cleannotes.app}"

echo "=== [1/2] Creating Cloud Run Domain Mapping for ${DOMAIN} ==="
gcloud beta run domain-mappings create \
    --service="${SERVICE_NAME}" \
    --domain="${DOMAIN}" \
    --region="${REGION}" \
    --platform=managed \
    --project="${PROJECT_ID}"

echo "=== [2/2] Fetching Required DNS Records ==="
echo "Add the following DNS records to your DNS provider (Cloudflare / Namecheap / Route53):"
echo "----------------------------------------------------------------------------------"
gcloud beta run domain-mappings describe \
    --domain="${DOMAIN}" \
    --region="${REGION}" \
    --platform=managed \
    --project="${PROJECT_ID}" \
    --format="table(records[].name, records[].type, records[].rrdata)"
echo "----------------------------------------------------------------------------------"
echo "SSL/TLS certificate will automatically provision once DNS propagation completes."
