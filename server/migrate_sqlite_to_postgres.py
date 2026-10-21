"""
CleanNotes PrintFlow POS — SQLite to PostgreSQL Migration Utility (Gate 9-1)
Enables zero-downtime migration to Supabase / Neon PostgreSQL when crossing 50 shops.
"""

import os
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger("shopkeeper.migration")

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
    machine_hash VARCHAR(64) PRIMARY KEY,
    shop_name VARCHAR(255),
    phone VARCHAR(32),
    tier VARCHAR(32) NOT NULL DEFAULT 'TRIAL',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    daily_limit INTEGER NOT NULL DEFAULT 50,
    license_key VARCHAR(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_ledger (
    machine_hash VARCHAR(64) NOT NULL,
    date DATE NOT NULL,
    pages_processed INTEGER NOT NULL DEFAULT 0,
    pdfs_processed INTEGER NOT NULL DEFAULT 0,
    toner_savings_inr NUMERIC(10, 2) NOT NULL DEFAULT 0.0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (machine_hash, date)
);

CREATE TABLE IF NOT EXISTS processed_webhooks (
    event_id VARCHAR(128) PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

def extract_sqlite_data(sqlite_path: str):
    """Extracts all table records from local SQLite database."""
    data = {"licenses": [], "usage_ledger": [], "processed_webhooks": []}
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        data["licenses"] = [dict(r) for r in cur.execute("SELECT * FROM licenses;").fetchall()]
        data["usage_ledger"] = [dict(r) for r in cur.execute("SELECT * FROM usage_ledger;").fetchall()]
        data["processed_webhooks"] = [dict(r) for r in cur.execute("SELECT * FROM processed_webhooks;").fetchall()]
    return data

def build_postgres_upsert_statements(data: dict) -> list[str]:
    """Generates PostgreSQL idempotent INSERT ... ON CONFLICT DO UPDATE statements."""
    statements = []
    for lic in data["licenses"]:
        stmt = f"""
        INSERT INTO shops (machine_hash, shop_name, phone, tier, is_active, registered_at, expires_at, daily_limit, license_key)
        VALUES ('{lic['machine_hash']}', '{lic.get('shop_name', '')}', '{lic.get('phone', '')}', '{lic['tier']}', 
                {bool(lic['is_active'])}, '{lic['registered_at']}', '{lic['expires_at']}', {lic['daily_limit']}, '{lic['license_key']}')
        ON CONFLICT (machine_hash) DO UPDATE SET
            tier = EXCLUDED.tier,
            is_active = EXCLUDED.is_active,
            expires_at = EXCLUDED.expires_at;
        """
        statements.append(stmt.strip())
    return statements
