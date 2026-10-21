# ==============================================================================
# CleanNotes PrintFlow POS (B2B Server) — Cloud Run Deployment Script (PowerShell)
# Self-contained within apps/shopkeeper-web/deploy/
# ==============================================================================

param(
    [string]$ProjectId = $env:GCP_PROJECT_ID,
    [string]$Region = "asia-south1",
    [string]$ServiceName = "cleannotes-b2b-pos"
)

if (-not $ProjectId) {
    $ProjectId = "cleannotes-prod"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Split-Path -Parent $ScriptDir
$ImageTag = "gcr.io/$ProjectId/${ServiceName}:latest"

Write-Host "=== [1/4] Validating GCP Configuration ===" -ForegroundColor Cyan
Write-Host "App Directory: $AppDir"
Write-Host "Project ID:    $ProjectId"
Write-Host "Region:        $Region (Mumbai)"
Write-Host "Service:       $ServiceName"

Write-Host "=== [2/4] Building Self-Contained Container Image ===" -ForegroundColor Cyan
docker build -f "$ScriptDir\Dockerfile" -t $ImageTag "$AppDir"
if ($LASTEXITCODE -ne 0) { throw "Docker build failed" }

Write-Host "=== [3/4] Pushing Container Image to Registry ===" -ForegroundColor Cyan
docker push $ImageTag
if ($LASTEXITCODE -ne 0) { throw "Docker push failed" }

Write-Host "=== [4/4] Deploying to Cloud Run ===" -ForegroundColor Cyan
gcloud run deploy $ServiceName `
    --image=$ImageTag `
    --platform=managed `
    --region=$Region `
    --allow-unauthenticated `
    --port=8001 `
    --min-instances=1 `
    --max-instances=10 `
    --cpu=2 `
    --memory=1Gi `
    --timeout=60s `
    --concurrency=8 `
    --set-env-vars="DOCUMORPH_ENV=production,ALLOWED_ORIGINS=https://cleannotes.app,https://cleannotes-pos.vercel.app" `
    --set-secrets="DOCUMORPH_B2B_SECRET=documorph-b2b-secret:latest,RAZORPAY_WEBHOOK_SECRET=razorpay-webhook-secret:latest"

if ($LASTEXITCODE -ne 0) { throw "Cloud Run deployment failed" }

Write-Host "=== Deployment Succeeded! Verifying Health Probe ===" -ForegroundColor Green
$ServiceUrl = gcloud run services describe $ServiceName --platform=managed --region=$Region --format="value(status.url)"
Invoke-RestMethod -Uri "$ServiceUrl/api/health"
Write-Host "CleanNotes PrintFlow POS is live at: $ServiceUrl" -ForegroundColor Green
