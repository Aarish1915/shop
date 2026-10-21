#!/usr/bin/env bash
# ==============================================================================
# CleanNotes PrintFlow POS — Secret Manager Provisioning Script
# Self-contained within apps/shopkeeper-web/deploy/
# ==============================================================================

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-cleannotes-prod}"

echo "=== Ensuring Secret Manager API is enabled in ${PROJECT_ID} ==="
gcloud services enable secretmanager.googleapis.com --project="${PROJECT_ID}"

echo "=== Provisioning 'documorph-b2b-secret' ==="
if gcloud secrets describe documorph-b2b-secret --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Secret documorph-b2b-secret already exists."
else
    gcloud secrets create documorph-b2b-secret \
        --replication-policy="automatic" \
        --project="${PROJECT_ID}"
    python3 -c "import secrets; print(secrets.token_hex(32))" | \
        gcloud secrets versions add documorph-b2b-secret --data-file=- --project="${PROJECT_ID}"
    echo "Provisioned fresh cryptographic master key for B2B license signing."
fi

echo "=== Provisioning 'razorpay-webhook-secret' ==="
if gcloud secrets describe razorpay-webhook-secret --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Secret razorpay-webhook-secret already exists."
else
    gcloud secrets create razorpay-webhook-secret \
        --replication-policy="automatic" \
        --project="${PROJECT_ID}"
    if [ -n "${RAZORPAY_WEBHOOK_SECRET:-}" ]; then
        echo -n "${RAZORPAY_WEBHOOK_SECRET}" | \
            gcloud secrets versions add razorpay-webhook-secret --data-file=- --project="${PROJECT_ID}"
    else
        echo "WARNING: Set RAZORPAY_WEBHOOK_SECRET to add version automatically."
    fi
fi

echo "=== Granting Secret Access to Cloud Run Default Service Account ==="
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud secrets add-iam-policy-binding documorph-b2b-secret \
    --member="serviceAccount:${RUN_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="${PROJECT_ID}"

gcloud secrets add-iam-policy-binding razorpay-webhook-secret \
    --member="serviceAccount:${RUN_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="${PROJECT_ID}"

echo "=== Secrets Setup Complete! ==="
