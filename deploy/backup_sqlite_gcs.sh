#!/usr/bin/env bash
# ==============================================================================
# CleanNotes PrintFlow POS — SQLite WAL Hot Snapshot Backup Automation (Gate 7-9)
# Performs non-blocking online atomic backup and uploads to Cloud Storage
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DB_PATH="${DOCUMORPH_B2B_DB:-${APP_DIR}/server/data/b2b.db}"
BACKUP_DIR="${APP_DIR}/server/data/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/b2b_backup_${TIMESTAMP}.sqlite"
GCS_BUCKET="${GCS_BACKUP_BUCKET:-gs://cleannotes-db-backups}"

mkdir -p "${BACKUP_DIR}"

echo "=== [1/3] Performing Online Atomic SQLite Snapshot ==="
if [ ! -f "${DB_PATH}" ]; then
    echo "Warning: Database not found at ${DB_PATH}. Exiting."
    exit 0
fi

# SQLite online backup API: locks safely without corrupting concurrent WAL writers
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"
echo "Created local snapshot: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))"

echo "=== [2/3] Uploading to Google Cloud Storage ==="
if command -v gsutil >/dev/null 2>&1; then
    gsutil cp "${BACKUP_FILE}" "${GCS_BUCKET}/"
    echo "Uploaded snapshot to ${GCS_BUCKET}/b2b_backup_${TIMESTAMP}.sqlite"
else
    echo "gsutil CLI not found in environment. Preserving local backup in ${BACKUP_DIR}."
fi

echo "=== [3/3] Pruning Local Backups Older Than 7 Days ==="
find "${BACKUP_DIR}" -name "b2b_backup_*.sqlite" -mtime +7 -delete || true
echo "Backup execution finished successfully."
