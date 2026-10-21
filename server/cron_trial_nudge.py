"""
Automated Day-5 WhatsApp Trial Conversion Nudge (Gate 8-5)
Queries shops nearing the end of their 7-day trial and dispatches conversion links.
"""

import sqlite3
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

def get_nudge_candidates(db_path: str):
    """Finds active TRIAL shops with exactly 2 days remaining (Day 5)."""
    candidates = []
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("""
            SELECT machine_hash, shop_name, phone, expires_at, tier
            FROM licenses
            WHERE tier = 'TRIAL' AND is_active = 1;
        """).fetchall()

        for r in rows:
            exp = datetime.fromisoformat(r["expires_at"])
            diff_days = (exp - now).total_seconds() / 86400
            # If between 1.0 and 2.5 days left, shop is on Day 5/6
            if 0 < diff_days <= 2.5:
                candidates.append(dict(r))
    return candidates

def generate_whatsapp_nudge_link(phone: str, shop_name: str) -> str:
    """Generates 1-tap WhatsApp message with Razorpay ₹499 UPI mandate link."""
    clean_phone = phone.replace("+", "").replace("-", "").strip() if phone else ""
    msg = (
        f"Namaste {shop_name}! Your CleanNotes PrintFlow 7-day trial ends in 48 hours. "
        "Keep saving ₹35,000+/mo on laser toner for just ₹499/month (₹16/day). "
        "Tap to activate auto-renewal via UPI: https://b2b.cleannotes.app/upgrade"
    )
    encoded = urllib.parse.quote(msg)
    return f"https://wa.me/{clean_phone}?text={encoded}"
