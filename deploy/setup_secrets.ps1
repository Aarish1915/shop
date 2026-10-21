# ==============================================================================
# CleanNotes PrintFlow POS — Secret Manager Provisioning Script (PowerShell)
# Self-contained within apps/shopkeeper-web/deploy/
# ==============================================================================

param(
    [string]$ProjectId = $env:GCP_PROJECT_ID
)

if (-not $ProjectId) {
    $ProjectId = "cleannotes-prod"
}

Write-Host "=== Ensuring Secret Manager API is enabled in $ProjectId ===" -ForegroundColor Cyan
gcloud services enable secretmanager.googleapis.com --project=$ProjectId

Write-Host "=== Provisioning 'documorph-b2b-secret' ===" -ForegroundColor Cyan
$existingSecret = gcloud secrets describe documorph-b2b-secret --project=$ProjectId 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "Secret documorph-b2b-secret already exists."
} else {
    gcloud secrets create documorph-b2b-secret --replication-policy="automatic" --project=$ProjectId
    $randomSecret = python -c "import secrets; print(secrets.token_hex(32))"
    [System.IO.File]::WriteAllText("$env:TEMP\b2b_sec.tmp", $randomSecret.Trim())
    gcloud secrets versions add documorph-b2b-secret --data-file="$env:TEMP\b2b_sec.tmp" --project=$ProjectId
    Remove-Item "$env:TEMP\b2b_sec.tmp" -Force
    Write-Host "Provisioned fresh cryptographic master key for B2B license signing." -ForegroundColor Green
}

Write-Host "=== Provisioning 'razorpay-webhook-secret' ===" -ForegroundColor Cyan
$existingRzp = gcloud secrets describe razorpay-webhook-secret --project=$ProjectId 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "Secret razorpay-webhook-secret already exists."
} else {
    gcloud secrets create razorpay-webhook-secret --replication-policy="automatic" --project=$ProjectId
    if ($env:RAZORPAY_WEBHOOK_SECRET) {
        [System.IO.File]::WriteAllText("$env:TEMP\rzp_sec.tmp", $env:RAZORPAY_WEBHOOK_SECRET.Trim())
        gcloud secrets versions add razorpay-webhook-secret --data-file="$env:TEMP\rzp_sec.tmp" --project=$ProjectId
        Remove-Item "$env:TEMP\rzp_sec.tmp" -Force
    } else {
        Write-Host "WARNING: Set RAZORPAY_WEBHOOK_SECRET to add version automatically." -ForegroundColor Yellow
    }
}

Write-Host "=== Granting Secret Access to Cloud Run Default Service Account ===" -ForegroundColor Cyan
$ProjectNumber = gcloud projects describe $ProjectId --format="value(projectNumber)"
$RunSa = "$ProjectNumber-compute@developer.gserviceaccount.com"

gcloud secrets add-iam-policy-binding documorph-b2b-secret `
    --member="serviceAccount:$RunSa" `
    --role="roles/secretmanager.secretAccessor" `
    --project=$ProjectId

gcloud secrets add-iam-policy-binding razorpay-webhook-secret `
    --member="serviceAccount:$RunSa" `
    --role="roles/secretmanager.secretAccessor" `
    --project=$ProjectId

Write-Host "=== Secrets Setup Complete! ===" -ForegroundColor Green
