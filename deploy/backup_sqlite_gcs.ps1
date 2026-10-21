# ==============================================================================
# CleanNotes PrintFlow POS — SQLite WAL Hot Snapshot Backup (PowerShell) (Gate 7-9)
# ==============================================================================

param(
    [string]$DbPath = $env:DOCUMORPH_B2B_DB,
    [string]$GcsBucket = $env:GCS_BACKUP_BUCKET
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Split-Path -Parent $ScriptDir

if (-not $DbPath) {
    $DbPath = Join-Path $AppDir "server\data\b2b.db"
}

$BackupDir = Join-Path $AppDir "server\data\backups"
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupFile = Join-Path $BackupDir "b2b_backup_$Timestamp.sqlite"

Write-Host "=== [1/3] Performing Online Atomic SQLite Snapshot ===" -ForegroundColor Cyan
if (-not (Test-Path $DbPath)) {
    Write-Host "Warning: Database not found at $DbPath. Exiting." -ForegroundColor Yellow
    exit 0
}

# Python SQLite backup API: standard library non-blocking atomic backup
python -c @"
import sqlite3
source = sqlite3.connect(r'$DbPath')
dest = sqlite3.connect(r'$BackupFile')
source.backup(dest)
dest.close()
source.close()
print('Snapshot created successfully.')
"@

Write-Host "Created local snapshot: $BackupFile" -ForegroundColor Green

Write-Host "=== [2/3] Checking Cloud Storage Sync ===" -ForegroundColor Cyan
if ($GcsBucket -and (Get-Command gsutil -ErrorAction SilentlyContinue)) {
    gsutil cp "$BackupFile" "$GcsBucket/"
    Write-Host "Uploaded snapshot to $GcsBucket" -ForegroundColor Green
} else {
    Write-Host "Cloud storage sync skipped. Local backup preserved at $BackupDir"
}

Write-Host "=== [3/3] Pruning Local Backups Older Than 7 Days ===" -ForegroundColor Cyan
Get-ChildItem -Path $BackupDir -Filter "b2b_backup_*.sqlite" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force
Write-Host "Backup execution completed." -ForegroundColor Green
