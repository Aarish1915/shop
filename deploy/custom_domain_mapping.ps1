# ==============================================================================
# CleanNotes PrintFlow POS — Custom Domain & SSL/TLS Mapping Automation (PowerShell)
# Maps pos.cleannotes.app to Google Cloud Run service with automated managed certificates
# ==============================================================================

param(
    [string]$Domain = "pos.cleannotes.app",
    [string]$ProjectId = $env:GCP_PROJECT_ID,
    [string]$Region = "asia-south1",
    [string]$ServiceName = "cleannotes-b2b-pos"
)

if (-not $ProjectId) {
    $ProjectId = "cleannotes-prod"
}

Write-Host "=== [1/2] Creating Cloud Run Domain Mapping for $Domain ===" -ForegroundColor Cyan
gcloud beta run domain-mappings create `
    --service=$ServiceName `
    --domain=$Domain `
    --region=$Region `
    --platform=managed `
    --project=$ProjectId

Write-Host "=== [2/2] Fetching Required DNS Records ===" -ForegroundColor Cyan
Write-Host "Add the following records to your DNS provider (Cloudflare / Namecheap):"
Write-Host "----------------------------------------------------------------------"
gcloud beta run domain-mappings describe `
    --domain=$Domain `
    --region=$Region `
    --platform=managed `
    --project=$ProjectId `
    --format="table(records[].name, records[].type, records[].rrdata)"
Write-Host "----------------------------------------------------------------------"
Write-Host "Managed SSL certificate will provision automatically upon DNS propagation." -ForegroundColor Green
