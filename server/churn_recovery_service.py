"""
CleanNotes PrintFlow POS — Churn Recovery & Retention Automation (Gate 9-5)
Identifies inactive Xerox counters and dispatches re-engagement offers.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

def identify_churn_risks(db_path: str, inactivity_days: int = 3) -> list[dict]:
    """Identifies shops registered but with 0 jobs processed in the last N days."""
    now = datetime.now(timezone.utc)
    cutoff_date = (now - timedelta(days=inactivity_days)).strftime("%Y-%m-%d")
    
    churn_shops = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Select all active shops
        shops = cur.execute("SELECT machine_hash, shop_name, phone, tier, registered_at FROM licenses WHERE is_active = 1").fetchall()
        for s in shops:
            m_hash = s["machine_hash"]
            recent_usage = cur.execute("""
                SELECT SUM(pages_processed) FROM usage_ledger 
                WHERE machine_hash = ? AND date >= ?
            """, (m_hash, cutoff_date)).fetchone()[0]
            
            if not recent_usage or recent_usage == 0:
                churn_shops.append({
                    "machine_hash": m_hash,
                    "shop_name": s["shop_name"],
                    "phone": s["phone"],
                    "tier": s["tier"],
                    "churn_status": "HIGH_RISK",
                    "reason": f"0 pages processed in last {inactivity_days} days"
                })
                
    return churn_shops
