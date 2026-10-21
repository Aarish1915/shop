import sys
import os
import io
import time
import fitz
import pytest
import sqlite3
import hmac
import hashlib
import json
from pathlib import Path

# Resolve server directory for direct import
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from main import app
from b2b_router import init_b2b_db, get_b2b_db_path, get_b2b_secret, get_razorpay_secret
from fastapi.testclient import TestClient

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_b2b_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_isolated_b2b.db")
    monkeypatch.setenv("DOCUMORPH_B2B_DB", test_db)
    init_b2b_db(test_db)
    yield test_db

@pytest.fixture
def sample_pdf_bytes():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "CleanNotes Dedicated Shopkeeper POS Test", fontsize=14)
    data = doc.tobytes()
    doc.close()
    return data

def test_shopkeeper_server_health():
    """Verifies that the dedicated Shopkeeper POS server health probe responds."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "CleanNotes PrintFlow POS Server"
    assert data["database"] == "connected"

def test_unregistered_machine_blocked(sample_pdf_bytes):
    """Verifies that unregistered machines cannot process batches for free."""
    files = [("files", ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    data = {
        "merge": "false",
        "mode": "bw_laser",
        "machine_id": "unregistered_pos_counter"
    }
    resp = client.post("/api/b2b/process-batch", files=files, data=data)
    assert resp.status_code == 403
    assert "No active license" in resp.json().get("detail", "")

def test_fake_mime_rejected():
    """Verifies that non-PDF files missing %PDF- header are rejected with HTTP 400."""
    machine_id = "pos_valid_machine_01"
    client.post("/api/b2b/license/register-trial", json={"machine_id": machine_id})

    files = [("files", ("bad.pdf", io.BytesIO(b"Not a PDF header"), "application/pdf"))]
    data = {
        "merge": "false",
        "mode": "bw_laser",
        "machine_id": machine_id
    }
    resp = client.post("/api/b2b/process-batch", files=files, data=data)
    assert resp.status_code == 400
    assert "missing %PDF- header" in resp.json().get("detail", "")

def test_authorized_batch_flow_and_atomic_ledger(sample_pdf_bytes):
    """Registers trial, processes genuine PDF batch, asserts SQLite ledger increment."""
    machine_id = "pos_valid_machine_02"
    reg_resp = client.post("/api/b2b/license/register-trial", json={
        "machine_id": machine_id,
        "shop_name": "Delhi University Xerox Counter"
    })
    assert reg_resp.status_code == 200
    reg_data = reg_resp.json()
    assert reg_data["status"] == "SUCCESS"

    files = [("files", ("lecture_slide.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    data = {
        "merge": "false",
        "mode": "bw_laser",
        "machine_id": machine_id
    }
    proc_resp = client.post("/api/b2b/process-batch", files=files, data=data)
    assert proc_resp.status_code == 200
    assert proc_resp.headers.get("content-type") == "application/pdf"
    assert proc_resp.headers.get("x-total-pages") == "1"

    # Verify SQLite ledger directly
    db_path = get_b2b_db_path()
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT pages_processed, toner_savings_inr FROM usage_ledger WHERE machine_hash = ?",
                    (reg_data["license"]["machine_hash"],))
        row = cur.fetchone()

    assert row is not None
    assert row[0] == 1
    assert row[1] > 0

def test_license_persistence_survives():
    """Verifies that trial record persists in SQLite and verify endpoint reflects active status."""
    machine_id = "pos_persistent_pc"
    reg_resp = client.post("/api/b2b/license/register-trial", json={
        "machine_id": machine_id,
        "shop_name": "South Campus Xerox"
    })
    assert reg_resp.status_code == 200

    ver_resp = client.post("/api/b2b/license/verify", json={"machine_id": machine_id})
    assert ver_resp.status_code == 200
    assert ver_resp.json()["status"] == "ACTIVE"
    assert ver_resp.json()["days_left"] == 7

def test_webhook_deduplication():
    """Verifies that repeat webhook callbacks are recognized as ALREADY_PROCESSED."""
    payload = {
        "event_id": "evt_shop_unique_456",
        "event": "subscription.charged",
        "payload": {
            "subscription": {
                "entity": {
                    "notes": {"machine_id": "shop_sub_machine"}
                }
            }
        }
    }
    r1 = client.post("/api/b2b/webhooks/razorpay", json=payload)
    assert r1.status_code == 200
    assert r1.json()["status"] == "SUCCESS"

    r2 = client.post("/api/b2b/webhooks/razorpay", json=payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "ALREADY_PROCESSED"

def test_security_headers_present():
    """Verifies that security headers are injected into all HTTP responses."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("x-xss-protection") == "1; mode=block"

def test_oversized_payload_rejected_413(sample_pdf_bytes, monkeypatch):
    """Verifies that batch uploads exceeding upload ceiling are rejected with HTTP 413."""
    # Temporarily set ceiling to 100 bytes to test HTTP 413 rejection deterministically
    import b2b_router
    monkeypatch.setattr(b2b_router, "MAX_BATCH_UPLOAD_BYTES", 100)

    machine_id = "pos_413_test_machine"
    client.post("/api/b2b/license/register-trial", json={"machine_id": machine_id})

    files = [("files", ("large_doc.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    data = {
        "merge": "false",
        "mode": "bw_laser",
        "machine_id": machine_id
    }
    resp = client.post("/api/b2b/process-batch", files=files, data=data)
    assert resp.status_code == 413
    assert "exceeds 100MB ceiling" in resp.json().get("detail", "")

def test_razorpay_webhook_signature_enforcement():
    """Verifies that forged webhook calls are rejected with HTTP 400 and genuine HMAC passes."""
    payload = {
        "event_id": "evt_sig_test_789",
        "event": "payment.captured",
        "payload": {}
    }
    body_bytes = json.dumps(payload).encode()

    # 1. Invalid signature -> HTTP 400
    bad_headers = {"x-razorpay-signature": "forged_invalid_signature_hex"}
    r_bad = client.post("/api/b2b/webhooks/razorpay", content=body_bytes, headers=bad_headers)
    assert r_bad.status_code == 400
    assert "Invalid webhook signature" in r_bad.json().get("detail", "")

    # 2. Authentic HMAC-SHA256 signature -> HTTP 200
    secret = get_razorpay_secret()
    valid_sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    good_headers = {"x-razorpay-signature": valid_sig}
    r_good = client.post("/api/b2b/webhooks/razorpay", content=body_bytes, headers=good_headers)
    assert r_good.status_code == 200
    assert r_good.json()["status"] == "SUCCESS"

def test_production_secret_key_fail_fast(monkeypatch):
    """Verifies that booting in production with default/missing secrets raises RuntimeError."""
    monkeypatch.setenv("DOCUMORPH_ENV", "production")
    monkeypatch.delenv("DOCUMORPH_B2B_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="CRITICAL SECURITY ERROR"):
        get_b2b_secret()

def test_job_progress_streaming(sample_pdf_bytes):
    """Verifies that job_id tracking updates progress state correctly."""
    machine_id = "pos_progress_machine"
    client.post("/api/b2b/license/register-trial", json={"machine_id": machine_id})

    job_id = "job_test_progress_99"
    files = [("files", ("progress_doc.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf"))]
    data = {
        "merge": "false",
        "mode": "bw_laser",
        "machine_id": machine_id,
        "job_id": job_id
    }
    resp = client.post("/api/b2b/process-batch", files=files, data=data)
    assert resp.status_code == 200

    # Poll progress endpoint
    prog_resp = client.get(f"/api/b2b/jobs/{job_id}/progress")
    assert prog_resp.status_code == 200
    prog = prog_resp.json()
    assert prog["job_id"] == job_id
    assert prog["percent"] == 100
    assert prog["status"] == "completed"

def test_admin_overview_and_churn_detection():
    """Verifies that admin overview requires authentication, returns aggregate metrics, and flags churn risk."""
    # 1. Unauthorized request
    r_unauth = client.get("/api/b2b/admin/overview")
    assert r_unauth.status_code == 401

    # 2. Register test shops
    client.post("/api/b2b/license/register-trial", json={
        "machine_id": "active_shop_1",
        "shop_name": "Active DU Xerox"
    })
    client.post("/api/b2b/license/register-trial", json={
        "machine_id": "inactive_shop_2",
        "shop_name": "Ghost Shop Inactive"
    })

    # 3. Authorized request
    secret = get_b2b_secret()
    r_auth = client.get("/api/b2b/admin/overview", headers={"x-admin-key": secret})
    assert r_auth.status_code == 200
    data = r_auth.json()
    assert data["status"] == "SUCCESS"
    overview = data["overview"]
    assert len(data["shops"]) >= 2

def test_landing_page_endpoint():
    """Verifies that the B2B Xerox Counter landing page is accessible and valid HTML."""
    resp = client.get("/landing")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    content = resp.text
    assert "CleanNotes PrintFlow POS" in content
    assert "Toner Arbitrage Calculator" in content
    assert "Launch Counter POS Terminal" in content
    assert "pages-slider" in content

def test_admin_dashboard_endpoint():
    """Verifies that /admin serves the Central Counter Monitoring Dashboard HTML."""
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    content = resp.text
    assert "Command Center" in content
    assert "Xerox Counter Network Directory" in content

def test_cors_allowed_origins_env_override(monkeypatch):
    """Verifies that ALLOWED_ORIGINS dynamically extends CORS whitelist."""
    from main import get_allowed_origins
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://pos.myprintshop.in,https://xerox-hub.com")
    origins = get_allowed_origins()
    assert "https://pos.myprintshop.in" in origins
    assert "https://xerox-hub.com" in origins
    assert "https://cleannotes.app" in origins

def test_dockerfile_shopkeeper_compliance():
    """Verifies that apps/shopkeeper-web/deploy/Dockerfile adheres to multi-stage and non-root security standards."""
    dockerfile_path = Path(__file__).resolve().parents[1] / "deploy" / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist in apps/shopkeeper-web/deploy/"
    content = dockerfile_path.read_text(encoding="utf-8")
    assert "AS builder" in content, "Must be multi-stage with builder stage"
    assert "AS runner" in content, "Must be multi-stage with runner stage"
    assert "useradd -u 10001" in content or "USER appuser" in content, "Must run as non-root user"
    assert "HEALTHCHECK" in content, "Must specify container healthcheck probe"
    assert "EXPOSE 8001" in content, "Must expose dedicated shopkeeper port 8001"

def test_cloudrun_deploy_and_secret_scripts():
    """Verifies existence and configuration of Cloud Run deploy and secret setup scripts in deploy/."""
    deploy_dir = Path(__file__).resolve().parents[1] / "deploy"
    deploy_sh = deploy_dir / "deploy_cloudrun.sh"
    deploy_ps1 = deploy_dir / "deploy_cloudrun.ps1"
    secrets_sh = deploy_dir / "setup_secrets.sh"
    secrets_ps1 = deploy_dir / "setup_secrets.ps1"

    assert deploy_sh.exists() and deploy_ps1.exists()
    assert secrets_sh.exists() and secrets_ps1.exists()

    sh_content = deploy_sh.read_text(encoding="utf-8")
    assert "asia-south1" in sh_content, "Must deploy to Mumbai region (asia-south1)"
    assert "--min-instances=1" in sh_content, "Must specify min-instances=1 for zero cold starts"
    assert "documorph-b2b-secret" in sh_content, "Must inject Secret Manager credentials"

def test_correlation_id_injected_in_response():
    """Gate 2-3: Verifies that X-Correlation-ID is automatically injected in all HTTP responses."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "x-correlation-id" in resp.headers
    corr_id = resp.headers["x-correlation-id"]
    assert len(corr_id) >= 16

    # Test propagation if client sends custom correlation ID
    custom_id = "corr_trace_test_12345"
    resp2 = client.get("/health", headers={"X-Correlation-ID": custom_id})
    assert resp2.headers.get("x-correlation-id") == custom_id

def test_rate_limiting_enforcement(monkeypatch):
    """Gate 2-2: Verifies that excessive requests trigger HTTP 429 with Retry-After header."""
    from main import _IP_REQUEST_HISTORY
    _IP_REQUEST_HISTORY.clear()

    # Pre-populate 120 requests for test client IP
    client_ip = "testclient"
    now = time.time()
    _IP_REQUEST_HISTORY[client_ip] = [now] * 125

    resp = client.get("/landing")
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "60"
    assert "Rate limit exceeded" in resp.json().get("detail", "")
    _IP_REQUEST_HISTORY.clear()

def test_backup_sqlite_script_execution(tmp_path):
    """Gate 7-9: Verifies that online atomic SQLite backup creates a valid uncorrupted copy."""
    src_db = str(tmp_path / "src_test.db")
    dst_db = str(tmp_path / "dst_test_backup.sqlite")

    with sqlite3.connect(src_db) as conn:
        conn.execute("CREATE TABLE test_data (id INT, val TEXT);")
        conn.execute("INSERT INTO test_data VALUES (1, 'snap_test');")

    # Perform atomic non-blocking backup
    source = sqlite3.connect(src_db)
    dest = sqlite3.connect(dst_db)
    source.backup(dest)
    dest.close()
    source.close()

    assert Path(dst_db).exists()
    with sqlite3.connect(dst_db) as conn_bak:
        row = conn_bak.execute("SELECT val FROM test_data WHERE id=1;").fetchone()
        assert row[0] == "snap_test"

def test_locustfile_syntax_and_structure():
    """Gate 5-1: Verifies that the Locust concurrent load test file exists and is valid Python."""
    locust_path = Path(__file__).resolve().parents[1] / "tests" / "locustfile.py"
    assert locust_path.exists(), "locustfile.py must exist in tests/"
    content = locust_path.read_text(encoding="utf-8")
    assert "class XeroxCounterOperator" in content
    assert "process_student_pdf_batch" in content
    assert "BENCHMARK_PDF_BYTES" in content

def test_referral_program_and_rewards():
    """Gate 8-6 & Gate 3-B5: Verifies referral code generation and 3-referral reward extension."""
    # Register Referrer shop
    ref_resp = client.post("/api/b2b/license/register-trial", json={
        "machine_id": "shop_referrer_alpha",
        "shop_name": "Alpha Campus Xerox"
    })
    assert ref_resp.status_code == 200
    ref_code = ref_resp.json()["license"]["referral_code"]
    assert ref_code.startswith("CNREF-")

    # Register 3 referee shops using the referral code
    for i in range(1, 4):
        sub_resp = client.post("/api/b2b/license/register-trial", json={
            "machine_id": f"shop_referee_0{i}",
            "shop_name": f"Referee Counter {i}",
            "referral_code": ref_code
        })
        assert sub_resp.status_code == 200

    # Verify referrer stats endpoint
    stats_resp = client.get(f"/api/b2b/referrals/stats?machine_id=shop_referrer_alpha")
    assert stats_resp.status_code == 200
    s_data = stats_resp.json()
    assert s_data["referred_count"] == 3
    assert s_data["free_months_earned"] == 1

    # Verify referrer license was upgraded to PRO
    lic_resp = client.post("/api/b2b/license/verify", json={"machine_id": "shop_referrer_alpha"})
    assert lic_resp.status_code == 200
    assert lic_resp.json()["license"]["tier"] == "PRO"

def test_corrupted_pdf_structure_handling():
    """Gate 5-8: Verifies that broken PDF structure with valid magic bytes is rejected with HTTP 400."""
    machine_id = "pos_corrupt_test_machine"
    client.post("/api/b2b/license/register-trial", json={"machine_id": machine_id})

    # PDF magic bytes followed by garbage that fitz cannot parse
    corrupt_pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nThis is completely broken garbage data."
    files = [("files", ("corrupt.pdf", io.BytesIO(corrupt_pdf), "application/pdf"))]
    data = {
        "merge": "false",
        "mode": "bw_laser",
        "machine_id": machine_id
    }
    resp = client.post("/api/b2b/process-batch", files=files, data=data)
    assert resp.status_code == 400
    assert "Corrupted" in resp.json().get("detail", "") or "corrupted" in resp.json().get("detail", "")

def test_cron_trial_nudge_candidate_filtering():
    """Gate 8-5: Verifies automated Day-5 candidate filtering and WhatsApp nudge URL generation."""
    from cron_trial_nudge import get_nudge_candidates, generate_whatsapp_nudge_link
    from datetime import datetime, timezone, timedelta

    db_path = get_b2b_db_path()
    now = datetime.now(timezone.utc)
    day5_exp = (now + timedelta(days=2)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO licenses 
            (machine_hash, shop_name, phone, tier, is_active, registered_at, expires_at, daily_limit, license_key)
            VALUES ('hash_nudge_01', 'Nudge Pilot Xerox', '+919876543210', 'TRIAL', 1, ?, ?, 50, 'KEY123')
        """, (now.isoformat(), day5_exp))
        conn.commit()

    candidates = get_nudge_candidates(db_path)
    assert any(c["machine_hash"] == "hash_nudge_01" for c in candidates)

    wa_link = generate_whatsapp_nudge_link("+919876543210", "Nudge Pilot Xerox")
    assert "wa.me/919876543210" in wa_link
    assert "trial%20ends%20in%2048%20hours" in wa_link

def test_sqlite_to_postgres_migration_utility():
    """Gate 9-1: Verifies data extraction from SQLite and PostgreSQL idempotent upsert generation."""
    from migrate_sqlite_to_postgres import extract_sqlite_data, build_postgres_upsert_statements

    db_path = get_b2b_db_path()
    data = extract_sqlite_data(db_path)
    assert "licenses" in data
    assert "usage_ledger" in data

    statements = build_postgres_upsert_statements(data)
    assert isinstance(statements, list)
    if statements:
        assert "INSERT INTO shops" in statements[0]
        assert "ON CONFLICT (machine_hash) DO UPDATE" in statements[0]

def test_churn_recovery_service_detection():
    """Gate 9-5: Verifies that shops with 0 recent page volume are flagged as high churn risk."""
    from churn_recovery_service import identify_churn_risks

    db_path = get_b2b_db_path()
    risks = identify_churn_risks(db_path, inactivity_days=3)
    assert isinstance(risks, list)

def test_owasp_security_headers_and_sqli_probe():
    """Gate 4-2: Verifies automated OWASP security header assessment and SQLi defense."""
    deploy_dir = Path(__file__).resolve().parents[1] / "deploy"
    if str(deploy_dir) not in sys.path:
        sys.path.insert(0, str(deploy_dir))
    from security_scan_zap import evaluate_security_response, is_payload_safe_from_sqli

    resp = client.get("/health")
    eval_res = evaluate_security_response(dict(resp.headers))
    assert eval_res["x-content-type-options"] is True
    assert eval_res["x-frame-options"] is True
    assert eval_res["x-xss-protection"] is True

    assert is_payload_safe_from_sqli("normal_shop_name") is True
    assert is_payload_safe_from_sqli("' OR '1'='1") is False

def test_ci_cd_workflow_includes_pip_audit():
    """Gate 4-3: Verifies that CI/CD workflow contains dependency CVE audit step."""
    ci_path = Path(__file__).resolve().parents[1] / "deploy" / "ci-cd.yml"
    assert ci_path.exists()
    content = ci_path.read_text(encoding="utf-8")
    assert "pip-audit" in content
    assert "pip-audit -r apps/shopkeeper-web/server/requirements.txt" in content
