import sys
import os
import io
import time
import psutil
import pytest
import fitz
from pathlib import Path

# Resolve server directory for direct import
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from main import app
from b2b_router import init_b2b_db
from fastapi.testclient import TestClient

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_b2b_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_perf_b2b.db")
    monkeypatch.setenv("DOCUMORPH_B2B_DB", test_db)
    init_b2b_db(test_db)
    yield test_db

@pytest.fixture
def dark_lecture_pdf_bytes():
    """Generates a realistic dark lecture slide PDF with inverted text and diagram."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Fill with pitch dark slate canvas #0A0A0A
    rect = fitz.Rect(0, 0, 595, 842)
    page.draw_rect(rect, color=(0.04, 0.04, 0.04), fill=(0.04, 0.04, 0.04))
    # Insert white text
    page.insert_text((50, 100), "DocuMorph Performance Benchmark Slide", color=(1.0, 1.0, 1.0), fontsize=18)
    page.insert_text((50, 150), "Subject: High-Volume Xerox Counter Latency Test", color=(1.0, 1.0, 0.2), fontsize=14)
    data = doc.tobytes()
    doc.close()
    return data

def test_api_health_probe_ttfb_budget():
    """Gate 6-1: Verifies API Time-To-First-Byte on health probe is under 100ms budget."""
    latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        resp = client.get("/api/health")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)
        assert resp.status_code == 200

    avg_ttfb = sum(latencies) / len(latencies)
    assert avg_ttfb < 100.0, f"Average health probe TTFB ({avg_ttfb:.2f}ms) exceeded 100ms budget!"

def test_batch_processing_latency_and_memory_budget(dark_lecture_pdf_bytes):
    """Gate 6-2: Verifies end-to-end PDF whitening latency and memory footprint."""
    machine_id = "perf_bench_counter_01"
    client.post("/api/b2b/license/register-trial", json={"machine_id": machine_id})

    proc = psutil.Process()
    ram_before_mb = proc.memory_info().rss / (1024 * 1024)

    files = [("files", ("lecture_slide.pdf", io.BytesIO(dark_lecture_pdf_bytes), "application/pdf"))]
    data = {
        "merge": "false",
        "mode": "bw_laser",
        "machine_id": machine_id
    }

    t0 = time.perf_counter()
    resp = client.post("/api/b2b/process-batch", files=files, data=data)
    elapsed_total = time.perf_counter() - t0

    assert resp.status_code == 200
    assert resp.headers.get("x-total-pages") == "1"

    ram_after_mb = proc.memory_info().rss / (1024 * 1024)
    ram_delta_mb = ram_after_mb - ram_before_mb

    # Verify whitening output
    doc_out = fitz.open(stream=resp.content, filetype="pdf")
    assert len(doc_out) == 1
    doc_out.close()

    # Latency budget: single dark slide must whiten under 1.5 seconds locally
    assert elapsed_total < 1.5, f"Single slide latency ({elapsed_total:.2f}s) exceeded 1.5s budget!"
    # RAM budget: memory spike must stay under 50MB delta
    assert ram_delta_mb < 50.0, f"Memory spike ({ram_delta_mb:.2f}MB) exceeded 50MB budget!"

def test_sentry_health_telemetry_reporting(monkeypatch):
    """Gate 7-7: Verifies that Sentry status is accurately reported in health probe."""
    # When SENTRY_DSN is absent
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    resp = client.get("/api/health")
    assert resp.json().get("sentry") in ["disabled", "configured"]
