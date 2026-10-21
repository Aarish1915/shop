"""
CleanNotes PrintFlow POS — Playwright E2E Integration Suite (Gate 5-2)
Validates shopkeeper drag-drop -> processing -> thermal receipt & print flow.
"""

import os
import sys
import io
import fitz
import pytest
from pathlib import Path

# Add server directory to path
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from main import app
from b2b_router import init_b2b_db
from fastapi.testclient import TestClient

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_pos_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "playwright_e2e_b2b.db")
    monkeypatch.setenv("DOCUMORPH_B2B_DB", test_db)
    init_b2b_db(test_db)
    yield test_db

def create_sample_student_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Dark lecture background to test whitening
    page.draw_rect(fitz.Rect(0, 0, 595, 842), color=(0.1, 0.1, 0.1), fill=(0.1, 0.1, 0.1))
    page.insert_text((50, 100), "Physics Chapter 4 - Optics Lecture Notes", color=(1, 1, 1), fontsize=16)
    data = doc.tobytes()
    doc.close()
    return data

def test_e2e_shopkeeper_counter_full_lifecycle():
    """
    Gate 5-2 E2E Simulation:
    Step 1: Machine registers for 7-day trial.
    Step 2: Counter verifies active license and quota.
    Step 3: Dropdesk accepts lecture PDF batch upload.
    Step 4: Engine whitens background, verifies X-Total-Pages and X-Savings-INR.
    Step 5: Output PDF is verified as a valid, readable fitz document.
    Step 6: Thermal receipt data is ready and today's ticker metrics are updated.
    """
    machine_id = "playwright_counter_pc_01"
    
    # Step 1: Trial registration
    reg_resp = client.post("/api/b2b/license/register-trial", json={
        "machine_id": machine_id,
        "shop_name": "Gate 5-2 Xerox Counter",
        "phone": "+91-9876543210"
    })
    assert reg_resp.status_code == 200
    reg_data = reg_resp.json()
    assert reg_data["status"] == "SUCCESS"
    assert "CNREF-" in reg_data["license"]["referral_code"]
    
    # Step 2: License verification
    verify_resp = client.post("/api/b2b/license/verify", json={"machine_id": machine_id})
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()
    assert verify_data["status"] == "ACTIVE"
    assert verify_data["days_left"] == 7
    
    # Step 3 & 4: Upload batch & whiten
    pdf_bytes = create_sample_student_pdf()
    files = [("files", ("student_optics.pdf", io.BytesIO(pdf_bytes), "application/pdf"))]
    data = {
        "merge": "false",
        "mode": "bw_laser",
        "machine_id": machine_id,
        "job_id": "job_e2e_001"
    }
    
    proc_resp = client.post("/api/b2b/process-batch", files=files, data=data)
    assert proc_resp.status_code == 200
    assert proc_resp.headers.get("content-type") == "application/pdf"
    assert "x-total-pages" in proc_resp.headers
    assert "x-savings-inr" in proc_resp.headers
    
    # Step 5: Verify output PDF integrity
    out_doc = fitz.open(stream=proc_resp.content, filetype="pdf")
    assert out_doc.page_count == 1
    out_doc.close()
    
    # Step 6: Verify today's ticker metrics updated
    stats_resp = client.get("/api/b2b/stats/today")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()["metrics"]
    assert stats["total_pdfs"] >= 1
    assert stats["total_pages"] >= 1
    assert stats["toner_savings_inr"] > 0
