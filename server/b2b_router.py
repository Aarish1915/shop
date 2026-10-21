import os
import sys
import time
import uuid
import hmac
import hashlib
import json
import logging
import tempfile
import shutil
import sqlite3
import math
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse, FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
import fitz

# Engine import: prefer self-contained local engine, fallback to monorepo root
try:
    from engine.shielded_inverter import ShieldedOpticalInverter
except ImportError:
    REPO_ROOT = Path(__file__).resolve().parents[3]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from documorph.core.shielded_inverter import ShieldedOpticalInverter

logger = logging.getLogger("shopkeeper.b2b_router")
b2b_executor = ThreadPoolExecutor(max_workers=4)
_ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}

b2b_router = APIRouter(prefix="/api/b2b", tags=["Xerox Shopkeeper B2B"])

# --- Machine-Locked Trial & License Configuration ---
TRIAL_DAYS = 7
TRIAL_DAILY_LIMIT = 150
PRO_DAILY_LIMIT = 5000

MAX_BATCH_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB ceiling (HTTP 413)

def get_b2b_secret() -> str:
    env = (os.getenv("DOCUMORPH_ENV") or os.getenv("ENV") or "development").lower()
    secret = os.getenv("DOCUMORPH_B2B_SECRET")
    if env == "production":
        if not secret or secret == "b2b_commercial_master_secret_key_2026":
            raise RuntimeError("CRITICAL SECURITY ERROR: DOCUMORPH_B2B_SECRET must be set to a secure custom key in production!")
    return secret or "b2b_commercial_master_secret_key_2026"

def get_razorpay_secret() -> str:
    env = (os.getenv("DOCUMORPH_ENV") or os.getenv("ENV") or "development").lower()
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if env == "production":
        if not secret or secret == "rzp_webhook_secret_documorph_499":
            raise RuntimeError("CRITICAL SECURITY ERROR: RAZORPAY_WEBHOOK_SECRET must be set to a secure custom key in production!")
    return secret or "rzp_webhook_secret_documorph_499"

# --- SQLite Persistent Storage Layer ---
def get_b2b_db_path() -> str:
    default_db = Path(__file__).parent / "data" / "b2b.db"
    path_str = os.getenv("DOCUMORPH_B2B_DB", str(default_db))
    db_path = Path(path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)

def init_b2b_db(db_path: Optional[str] = None) -> None:
    path = db_path or get_b2b_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                machine_hash TEXT PRIMARY KEY,
                shop_name TEXT,
                phone TEXT,
                tier TEXT NOT NULL DEFAULT 'TRIAL',
                is_active INTEGER NOT NULL DEFAULT 1,
                registered_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                daily_limit INTEGER NOT NULL DEFAULT 50,
                license_key TEXT NOT NULL,
                referral_code TEXT,
                referred_by TEXT
            );
        """)
        # Ensure referral columns exist for backward compatibility
        cur = conn.cursor()
        cols = [c[1] for c in cur.execute("PRAGMA table_info(licenses)").fetchall()]
        if "referral_code" not in cols:
            conn.execute("ALTER TABLE licenses ADD COLUMN referral_code TEXT;")
        if "referred_by" not in cols:
            conn.execute("ALTER TABLE licenses ADD COLUMN referred_by TEXT;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_ledger (
                machine_hash TEXT NOT NULL,
                date TEXT NOT NULL,
                pages_processed INTEGER NOT NULL DEFAULT 0,
                pdfs_processed INTEGER NOT NULL DEFAULT 0,
                toner_savings_inr REAL NOT NULL DEFAULT 0.0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (machine_hash, date)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_webhooks (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.commit()

# Ensure DB initialized on module import
init_b2b_db()

def _get_license(machine_hash: str) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(get_b2b_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM licenses WHERE machine_hash = ?", (machine_hash,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_active"] = bool(d["is_active"])
        return d

def _save_license(record: Dict[str, Any]) -> None:
    with sqlite3.connect(get_b2b_db_path()) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO licenses 
            (machine_hash, shop_name, phone, tier, is_active, registered_at, expires_at, daily_limit, license_key, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record["machine_hash"],
            record.get("shop_name", "Campus Xerox"),
            record.get("phone"),
            record.get("tier", "TRIAL"),
            1 if record.get("is_active", True) else 0,
            record["registered_at"],
            record["expires_at"],
            record.get("daily_limit", TRIAL_DAILY_LIMIT),
            record["license_key"],
            record.get("referral_code"),
            record.get("referred_by")
        ))
        conn.commit()

def _get_today_pages(machine_hash: str, today_str: str) -> int:
    with sqlite3.connect(get_b2b_db_path()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT pages_processed FROM usage_ledger WHERE machine_hash = ? AND date = ?", 
                    (machine_hash, today_str))
        row = cur.fetchone()
        return row[0] if row else 0

def _record_usage(machine_hash: str, pdf_count: int, page_count: int, savings_inr: float) -> None:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with sqlite3.connect(get_b2b_db_path()) as conn:
        conn.execute("""
            INSERT INTO usage_ledger (machine_hash, date, pages_processed, pdfs_processed, toner_savings_inr, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(machine_hash, date) DO UPDATE SET
                pages_processed = pages_processed + excluded.pages_processed,
                pdfs_processed = pdfs_processed + excluded.pdfs_processed,
                toner_savings_inr = toner_savings_inr + excluded.toner_savings_inr,
                updated_at = datetime('now');
        """, (machine_hash, today_str, page_count, pdf_count, savings_inr))
        conn.commit()

def _check_and_mark_webhook(event_id: str) -> bool:
    with sqlite3.connect(get_b2b_db_path()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT event_id FROM processed_webhooks WHERE event_id = ?", (event_id,))
        if cur.fetchone():
            return True
        conn.execute("INSERT INTO processed_webhooks (event_id, processed_at) VALUES (?, datetime('now'))", (event_id,))
        conn.commit()
        return False

# --- Pydantic Schemas ---
class TrialRegisterRequest(BaseModel):
    machine_id: str = Field(..., description="Unique Windows machine-guid or hardware hash")
    shop_name: Optional[str] = Field("Campus Xerox", description="Shop name")
    phone: Optional[str] = Field(None, description="Shopkeeper phone number")
    referral_code: Optional[str] = Field(None, description="Referral code from peer shop")

class LicenseVerifyRequest(BaseModel):
    machine_id: str
    license_key: Optional[str] = None

class CreateSubscriptionRequest(BaseModel):
    machine_id: str
    shop_name: str
    phone: str
    plan_id: str = "plan_CleanNotes_Shop_499"


def _generate_license_key(machine_id: str, tier: str, expires_at: datetime) -> str:
    payload = f"{machine_id}:{tier}:{int(expires_at.timestamp())}"
    secret = get_b2b_secret()
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"CN-{tier[:4].upper()}-{sig.upper()}"


@b2b_router.post("/license/register-trial")
async def register_trial(req: TrialRegisterRequest):
    """Registers a 7-day hardware-locked trial for a Xerox shopkeeper counter PC with referral tracking (Gate 8-6)."""
    machine_hash = hashlib.sha256(req.machine_id.encode()).hexdigest()
    existing = _get_license(machine_hash)
    
    if existing:
        return {
            "status": "EXISTS",
            "message": "Trial already registered for this counter PC",
            "license": existing
        }
        
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=TRIAL_DAYS)
    license_key = _generate_license_key(machine_hash, "TRIAL", expires_at)
    
    # Generate unique referral code for this counter shop
    my_referral_code = f"CNREF-{machine_hash[:6].upper()}"
    referred_by_hash = None
    
    # Evaluate peer referral code if provided
    if req.referral_code:
        with sqlite3.connect(get_b2b_db_path()) as conn:
            cur = conn.cursor()
            cur.execute("SELECT machine_hash, tier, expires_at FROM licenses WHERE referral_code = ?", (req.referral_code.strip().upper(),))
            referrer = cur.fetchone()
            if referrer:
                referred_by_hash = referrer[0]
                cur.execute("SELECT COUNT(*) FROM licenses WHERE referred_by = ?", (referred_by_hash,))
                ref_count = cur.fetchone()[0] + 1
                # Gate 8-6: Every 3 referrals grant 1 free month (30 days) of Pro tier
                if ref_count % 3 == 0:
                    ref_exp = datetime.fromisoformat(referrer[2])
                    new_exp = max(now, ref_exp) + timedelta(days=30)
                    conn.execute("UPDATE licenses SET tier = 'PRO', expires_at = ?, daily_limit = ? WHERE machine_hash = ?",
                                 (new_exp.isoformat(), PRO_DAILY_LIMIT, referred_by_hash))
                    conn.commit()
    
    record = {
        "machine_hash": machine_hash,
        "shop_name": req.shop_name or "Campus Xerox",
        "phone": req.phone,
        "tier": "TRIAL",
        "is_active": True,
        "registered_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "daily_limit": TRIAL_DAILY_LIMIT,
        "license_key": license_key,
        "referral_code": my_referral_code,
        "referred_by": referred_by_hash
    }
    _save_license(record)
    
    return {
        "status": "SUCCESS",
        "message": f"7-day trial activated for {record['shop_name']}",
        "license": record
    }


@b2b_router.get("/referrals/stats")
async def get_referral_stats(machine_id: str):
    """Gate 8-6: Returns shopkeeper referral code, total shops referred, and rewards earned."""
    machine_hash = hashlib.sha256(machine_id.encode()).hexdigest()
    lic = _get_license(machine_hash)
    if not lic:
        raise HTTPException(status_code=404, detail="Machine not registered")
    
    ref_code = lic.get("referral_code") or f"CNREF-{machine_hash[:6].upper()}"
    with sqlite3.connect(get_b2b_db_path()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM licenses WHERE referred_by = ?", (machine_hash,))
        count = cur.fetchone()[0]
    
    months_earned = count // 3
    return {
        "status": "SUCCESS",
        "machine_id": machine_id,
        "referral_code": ref_code,
        "referred_count": count,
        "free_months_earned": months_earned,
        "next_reward_in": 3 - (count % 3),
        "share_url": f"https://cleannotes.app/landing?ref={ref_code}"
    }


@b2b_router.post("/license/verify")
async def verify_license(req: LicenseVerifyRequest):
    """Verifies counter PC license status, days remaining, and fair-use limits from SQLite."""
    machine_hash = hashlib.sha256(req.machine_id.encode()).hexdigest()
    lic = _get_license(machine_hash)
    
    if not lic:
        return {
            "status": "UNREGISTERED",
            "is_active": False,
            "message": "No active license found for this machine. Register for a 7-day trial or upgrade to Pro."
        }
        
    exp = datetime.fromisoformat(lic["expires_at"])
    now = datetime.now(timezone.utc)
    
    if now > exp:
        lic["is_active"] = False
        _save_license(lic)
        return {
            "status": "EXPIRED",
            "is_active": False,
            "message": "Trial or subscription expired. Please subscribe to Pro for ₹499/month.",
            "license": lic
        }
        
    days_left = max(0, math.ceil((exp - now).total_seconds() / 86400))
    return {
        "status": "ACTIVE",
        "is_active": True,
        "days_left": days_left,
        "license": lic
    }


@b2b_router.get("/stats/today")
async def get_today_stats():
    """Returns live aggregate ticker metrics from SQLite usage_ledger for the DropDesk counter dashboard."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with sqlite3.connect(get_b2b_db_path()) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(pdfs_processed), 0), 
                   COALESCE(SUM(pages_processed), 0), 
                   COALESCE(SUM(toner_savings_inr), 0.0) 
            FROM usage_ledger 
            WHERE date = ?
        """, (today_str,))
        row = cur.fetchone()
        total_pdfs, total_pages, total_savings = row if row else (0, 0, 0.0)
        
    return {
        "status": "SUCCESS",
        "metrics": {
            "date": today_str,
            "total_pdfs": total_pdfs,
            "total_pages": total_pages,
            "toner_savings_inr": round(total_savings, 2),
            "estimated_co2_kg_saved": round(total_pages * 0.0045, 2)
        }
    }


@b2b_router.post("/process-batch")
async def process_batch(
    files: List[UploadFile] = File(...),
    merge: bool = Form(True),
    mode: str = Form("bw_laser"),
    machine_id: str = Form(...),
    job_id: Optional[str] = Form(None)
):
    """
    High-capacity batch ingestion for Xerox shopkeepers.
    Guarded by license verification and fair-use daily quotas.
    Cleans up all temporary files on completion.
    """
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 PDFs allowed per batch in DropDesk")
        
    # --- License Verification Gate ---
    machine_hash = hashlib.sha256(machine_id.encode()).hexdigest()
    lic = _get_license(machine_hash)
    if not lic or not lic.get("is_active"):
        raise HTTPException(
            status_code=403, 
            detail="No active license found for this machine. Register for a 7-day trial or upgrade to Pro."
        )
    exp = datetime.fromisoformat(lic["expires_at"])
    if datetime.now(timezone.utc) > exp:
        raise HTTPException(
            status_code=403, 
            detail="Trial or subscription expired. Please subscribe to Pro for ₹499/month."
        )
        
    # Check Daily Fair-Use Limit
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pages_today = _get_today_pages(machine_hash, today_str)
    if pages_today >= lic.get("daily_limit", TRIAL_DAILY_LIMIT):
        raise HTTPException(
            status_code=429,
            detail=f"Daily quota of {lic.get('daily_limit')} pages reached for today. Upgrade plan or wait until tomorrow."
        )

    t0 = time.time()
    temp_dir = tempfile.mkdtemp(prefix="b2b_batch_")
    saved_inputs = []
    total_batch_bytes = 0
    
    try:
        # 1. Save uploaded streams to disk, enforce 100MB ceiling & validate PDF magic bytes
        for idx, file in enumerate(files):
            filename = file.filename or f"doc_{idx+1}.pdf"
            in_path = os.path.join(temp_dir, f"in_{idx}_{filename}")
            first_chunk = True
            with open(in_path, "wb") as buffer:
                while chunk := await file.read(1024 * 1024):
                    total_batch_bytes += len(chunk)
                    if total_batch_bytes > MAX_BATCH_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="Total batch payload exceeds 100MB ceiling (HTTP 413)"
                        )
                    if first_chunk:
                        if not chunk.startswith(b"%PDF-"):
                            raise HTTPException(
                                status_code=400,
                                detail=f"File {filename} is not a valid PDF document (missing %PDF- header)"
                            )
                        first_chunk = False
                    buffer.write(chunk)
            saved_inputs.append(in_path)
            
        # 2. Merge or whiten
        try:
            if merge and len(saved_inputs) > 1:
                merged_in = os.path.join(temp_dir, "merged_input.pdf")
                doc_merge = fitz.open()
                for p in saved_inputs:
                    d = fitz.open(p)
                    doc_merge.insert_pdf(d)
                    d.close()
                doc_merge.save(merged_in)
                doc_merge.close()
                target_to_process = merged_in
            else:
                target_to_process = saved_inputs[0]
                test_doc = fitz.open(target_to_process)
                if test_doc.page_count == 0:
                    test_doc.close()
                    raise HTTPException(status_code=400, detail="PDF has 0 pages or empty structure")
                test_doc.close()
        except fitz.FileDataError as e:
            raise HTTPException(status_code=400, detail=f"Corrupted PDF structure: {str(e)}")
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=400, detail=f"Invalid or corrupted PDF file: {str(e)}")
            
        output_pdf = os.path.join(temp_dir, f"CLEANNOTES_BATCH_{int(time.time())}.pdf")
        
        def on_progress(p: int, total: int):
            if job_id:
                _ACTIVE_JOBS[job_id] = {
                    "job_id": job_id,
                    "page": p,
                    "total": total,
                    "percent": int((p / max(1, total)) * 100),
                    "status": "processing"
                }

        # 3. Execute Shielded Optical Inverter in executor (non-blocking event loop)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            b2b_executor,
            lambda: ShieldedOpticalInverter.process_pdf(
                input_pdf_path=target_to_process,
                output_pdf_path=output_pdf,
                zoom=1.25,
                mode=mode,
                whiten_borders=True,
                window_size=10,
                progress_callback=on_progress
            )
        )
        
        if job_id:
            _ACTIVE_JOBS[job_id] = {
                "job_id": job_id,
                "page": result["page_count"],
                "total": result["page_count"],
                "percent": 100,
                "status": "completed",
                "elapsed_seconds": result["elapsed_seconds"]
            }
        
        # 4. Atomic record in SQLite usage_ledger
        pages = result["page_count"]
        savings = pages * 4.15
        _record_usage(machine_hash, len(files), pages, savings)
        
        # 5. Guaranteed cleanup using BackgroundTask after response is streamed
        cleanup_task = BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True)
        
        return FileResponse(
            path=output_pdf,
            media_type="application/pdf",
            filename=f"WHITENED_{Path(output_pdf).name}",
            headers={
                "X-Total-Pages": str(pages),
                "X-Elapsed-Seconds": str(result["elapsed_seconds"]),
                "X-Savings-INR": str(round(savings, 2))
            },
            background=cleanup_task
        )
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error in B2B batch processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch processing error: {str(e)}")


@b2b_router.post("/subscription/create")
async def create_subscription(req: CreateSubscriptionRequest):
    """Creates Razorpay UPI Autopay mandate for ₹499/mo commercial subscription."""
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    qr_payload = f"upi://pay?pa=razorpay.cleannotes@icici&pn=CleanNotes%20B2B&am=499.00&cu=INR&tn=DropDesk%20Pro%20{req.shop_name}"
    
    return {
        "status": "CREATED",
        "subscription_id": sub_id,
        "amount_inr": 499.0,
        "plan": "CleanNotes DropDesk Pro Monthly",
        "upi_intent_url": qr_payload,
        "qr_code_data": qr_payload,
        "instructions": "Scan with PhonePe, Google Pay, or Paytm to set up ₹499 monthly recurring mandate."
    }


@b2b_router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    """Idempotent webhook listener for Razorpay UPI Autopay subscription events."""
    signature = request.headers.get("x-razorpay-signature", "")
    body_bytes = await request.body()
    
    expected_sig = hmac.new(
        get_razorpay_secret().encode(),
        body_bytes,
        hashlib.sha256
    ).hexdigest()
    
    is_prod = (os.getenv("DOCUMORPH_ENV") or os.getenv("ENV") or "").lower() == "production"
    skip_verify = os.getenv("DOCUMORPH_SKIP_WEBHOOK_VERIFY", "0") == "1"
    
    if not skip_verify:
        if is_prod and not signature:
            raise HTTPException(status_code=400, detail="Missing required x-razorpay-signature header")
        if signature and not hmac.compare_digest(signature, expected_sig):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
        
    try:
        data = json.loads(body_bytes.decode())
    except Exception:
        data = {}
        
    event_id = data.get("event_id") or data.get("id") or hashlib.md5(body_bytes).hexdigest()
    
    if _check_and_mark_webhook(event_id):
        return {"status": "ALREADY_PROCESSED"}
        
    event_type = data.get("event", "subscription.charged")
    
    if event_type in ("subscription.charged", "payment.captured"):
        payload = data.get("payload", {})
        sub = payload.get("subscription", {}).get("entity", {})
        machine_id = sub.get("notes", {}).get("machine_id", "default_machine")
        machine_hash = hashlib.sha256(machine_id.encode()).hexdigest()
        
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=30)
        license_key = _generate_license_key(machine_hash, "PRO", expires_at)
        
        _save_license({
            "machine_hash": machine_hash,
            "shop_name": sub.get("notes", {}).get("shop_name", "CleanNotes Pro Shop"),
            "phone": sub.get("notes", {}).get("phone"),
            "tier": "PRO",
            "is_active": True,
            "registered_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "daily_limit": PRO_DAILY_LIMIT,
            "license_key": license_key
        })
        logger.info(f"Activated Pro license in SQLite for machine {machine_id} until {expires_at.isoformat()}")
        
    return {"status": "SUCCESS", "event_id": event_id}


@b2b_router.get("/jobs/{job_id}/progress")
async def get_job_progress(job_id: str):
    """Returns real-time progress for an active batch whitening job."""
    job = _ACTIVE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job


@b2b_router.get("/admin/overview")
async def get_admin_overview(request: Request):
    """
    Administrative overview: shops list, active licenses, today's aggregate metrics,
    and automated churn risk detection (shops inactive for >= 3 days).
    Protected by X-Admin-Key.
    """
    admin_key = request.headers.get("x-admin-key") or request.query_params.get("admin_key")
    expected_key = get_b2b_secret()
    if not admin_key or not hmac.compare_digest(admin_key, expected_key):
        raise HTTPException(status_code=401, detail="Unauthorized admin access")

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_dt = datetime.now(timezone.utc).date()
    
    with sqlite3.connect(get_b2b_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 1. Total shops & active count
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) FROM licenses")
        row = cur.fetchone()
        total_shops = row[0] or 0
        active_shops = row[1] or 0
        
        # 2. Today's aggregate metrics
        cur.execute("SELECT COALESCE(SUM(pages_processed), 0), COALESCE(SUM(toner_savings_inr), 0.0) FROM usage_ledger WHERE date = ?", (today_str,))
        today_row = cur.fetchone()
        today_pages = today_row[0] or 0
        today_savings = round(today_row[1] or 0.0, 2)
        
        # 3. Shops detailed list with churn alerts
        cur.execute("""
            SELECT l.machine_hash, l.shop_name, l.phone, l.tier, l.is_active, l.expires_at, l.registered_at,
                   MAX(u.date) as last_active_date,
                   COALESCE(SUM(u.pages_processed), 0) as total_pages,
                   COALESCE(SUM(u.toner_savings_inr), 0.0) as total_savings
            FROM licenses l
            LEFT JOIN usage_ledger u ON l.machine_hash = u.machine_hash
            GROUP BY l.machine_hash
            ORDER BY l.registered_at DESC
        """)
        shops_list = []
        for r in cur.fetchall():
            last_date_str = r["last_active_date"]
            churn_risk = False
            churn_reason = None
            if not last_date_str:
                churn_risk = True
                churn_reason = "No jobs ever processed since registration"
            else:
                last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
                days_inactive = (today_dt - last_date).days
                if days_inactive >= 3:
                    churn_risk = True
                    churn_reason = f"No activity in past {days_inactive} days (Call shopkeeper)"
            
            exp_dt = datetime.fromisoformat(r["expires_at"])
            days_left = max(0, math.ceil((exp_dt - datetime.now(timezone.utc)).total_seconds() / 86400))
            
            shops_list.append({
                "machine_hash": r["machine_hash"],
                "shop_name": r["shop_name"],
                "phone": r["phone"],
                "tier": r["tier"],
                "is_active": bool(r["is_active"]),
                "days_left": days_left,
                "last_active_date": last_date_str,
                "total_pages": r["total_pages"],
                "total_savings_inr": round(r["total_savings"], 2),
                "churn_risk": churn_risk,
                "churn_reason": churn_reason
            })

    return {
        "status": "SUCCESS",
        "overview": {
            "total_shops": total_shops,
            "active_shops": active_shops,
            "today_pages": today_pages,
            "today_savings_inr": today_savings,
            "churn_count": sum(1 for s in shops_list if s["churn_risk"])
        },
        "shops": shops_list
    }
