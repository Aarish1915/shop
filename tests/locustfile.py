"""
Locust Load Testing Suite for CleanNotes PrintFlow POS (Gate 5-1)
Simulates 10 concurrent Indian Xerox shopkeepers processing lecture PDF batches simultaneously.
"""

import io
from locust import HttpUser, task, between
import fitz

def generate_bench_pdf():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rect = fitz.Rect(0, 0, 595, 842)
    page.draw_rect(rect, color=(0.05, 0.05, 0.05), fill=(0.05, 0.05, 0.05))
    page.insert_text((50, 100), "CleanNotes Concurrent POS Load Test", color=(1.0, 1.0, 1.0), fontsize=16)
    data = doc.tobytes()
    doc.close()
    return data

BENCHMARK_PDF_BYTES = generate_bench_pdf()

class XeroxCounterOperator(HttpUser):
    wait_time = between(1, 3)  # Real-world pause between walk-in student jobs

    def on_start(self):
        """Auto-register machine trial on counter start."""
        self.machine_id = f"locust_counter_{self.environment.runner.user_count if self.environment.runner else 1}"
        self.client.post("/api/b2b/license/register-trial", json={
            "machine_id": self.machine_id,
            "shop_name": "University Load Test Xerox"
        })

    @task(3)
    def check_health_and_today_metrics(self):
        """Counter dashboard heartbeat: polls health and ticker stats."""
        self.client.get("/api/health")
        self.client.get("/api/b2b/stats/today")

    @task(1)
    def process_student_pdf_batch(self):
        """Processes a student batch upload and checks response headers."""
        files = [("files", ("student_lecture.pdf", io.BytesIO(BENCHMARK_PDF_BYTES), "application/pdf"))]
        data = {
            "merge": "false",
            "mode": "bw_laser",
            "machine_id": self.machine_id,
            "job_id": f"job_locust_{self.machine_id}"
        }
        with self.client.post("/api/b2b/process-batch", files=files, data=data, catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Batch failed with status {resp.status_code}")
