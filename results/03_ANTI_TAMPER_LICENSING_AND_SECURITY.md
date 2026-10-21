# 03. Anti-Tamper Licensing & Security Verification Report
**Date:** 2026-10-21  
**Target:** `documorph/api/b2b_router.py` & Security Boundary  
**Verification Status:** VERIFIED (TDD: 4/4 Tests PASS, Anti-Tamper: PASS)

---

## 1. P0-1: License Verification Gate on `/process-batch`
### Vulnerability Identified:
The `/api/b2b/process-batch` endpoint accepted any request without checking machine registration, allowing free processing without limits.

### Hardened Implementation:
Every call to `process-batch` now executes a mandatory hardware verification check before opening any PDF:
1. `machine_hash = hashlib.sha256(machine_id.encode()).hexdigest()`
2. Queries SQLite `licenses` table for active status.
3. If unverified: rejects with `HTTP 403 Forbidden`.
4. If expired: updates database status and rejects with `HTTP 403 Forbidden`.
5. Checks fair-use daily limits: if today's usage exceeds tier threshold (50 pages/day trial, 5,000 pages/day pro), rejects with `HTTP 429 Too Many Requests`.

---

## 2. Microsecond Boundary & Clock Fix
During Ralph Loop adversarial review, a microsecond boundary failure was discovered where integer division `(exp - now).days` truncated 6 days 23 hours into `6`, reporting an incorrect number of days remaining on newly registered trials.
- **Fix:** Switched to `max(0, math.ceil((exp - now).total_seconds() / 86400))`.
- **Result:** Accurate 7-day display on trial counter PCs.

---

## 3. Webhook Idempotency & Replay Defense
Razorpay subscription callbacks (`subscription.charged`, `payment.captured`) are tracked in the SQLite table `processed_webhooks`. Repeated webhook deliveries for the same `event_id` are halted with `{"status": "ALREADY_PROCESSED"}`, preventing double-crediting or race conditions.

---

## 4. TDD Verification Output
```bash
python -m pytest tests/integration/test_b2b_hardened.py -v
============================= test session starts =============================
tests/integration/test_b2b_hardened.py::test_process_batch_unregistered_machine_blocked PASSED [ 25%]
tests/integration/test_b2b_hardened.py::test_trial_registration_and_authorized_batch_flow PASSED [ 50%]
tests/integration/test_b2b_hardened.py::test_license_persistence_survives_restart PASSED [ 75%]
tests/integration/test_b2b_hardened.py::test_webhook_idempotency_persisted PASSED [100%]
======================== 4 passed, 6 warnings in 0.85s ========================
```
- **Exit Code:** 0
- **Status:** 100% PASS
