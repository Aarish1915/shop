import pytest
import os
import json
from pathlib import Path

def test_pwa_manifest_compliance():
    """Verifies that the PWA manifest contains required keys and Web Share Target for WhatsApp."""
    manifest_path = Path("apps/shopkeeper-web/public/manifest.json")
    assert manifest_path.exists(), "PWA manifest.json is missing!"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    assert data["name"] == "CleanNotes DropDesk — Xerox POS"
    assert data["display"] == "standalone"
    assert "share_target" in data, "Web Share Target is required for receiving WhatsApp PDFs!"
    assert data["share_target"]["action"] == "/api/b2b/process-batch"
    assert "files" in data["share_target"]["params"]

def test_service_worker_existence():
    """Verifies that the service worker exists for offline resilience."""
    sw_path = Path("apps/shopkeeper-web/public/sw.js")
    assert sw_path.exists(), "Service worker sw.js is missing!"
    content = sw_path.read_text(encoding="utf-8")
    assert "dropdesk-v3.0" in content
    assert "caches.open" in content

def test_thermal_receipt_print_css_rules():
    """Verifies that styles.css contains @media print rules targeting #thermal-receipt."""
    css_path = Path("apps/shopkeeper-web/src/styles.css")
    assert css_path.exists(), "styles.css is missing!"
    content = css_path.read_text(encoding="utf-8")
    assert "@media print" in content, "Print media query is missing!"
    assert "#thermal-receipt" in content, "Target #thermal-receipt ID is missing from print stylesheet!"
    assert "78mm" in content, "78mm standard thermal paper width is required for POS receipt roll!"
    assert "visibility: hidden" in content, "Must hide parent page elements during receipt printing!"

def test_app_tsx_pos_ergonomics_and_receipt():
    """Verifies that App.tsx implements POS hotkeys, split layout, and thermal voucher modal."""
    app_path = Path("apps/shopkeeper-web/src/App.tsx")
    assert app_path.exists(), "App.tsx is missing!"
    content = app_path.read_text(encoding="utf-8")
    assert "showReceiptModal" in content, "Receipt modal state is missing!"
    assert 'id="thermal-receipt"' in content, "DOM element #thermal-receipt is missing!"
    assert "TONER ARBITRAGE SAVED" in content, "Receipt must show toner arbitrage savings for customer proof!"
    assert "handleKeyDown" in content, "Global keyboard shortcuts required for counter velocity!"

def test_license_status_widget_present():
    """Gate 3-B2: Verifies that App.tsx renders the interactive license & quota status widget."""
    app_path = Path("apps/shopkeeper-web/src/App.tsx")
    content = app_path.read_text(encoding="utf-8")
    assert 'id="license-status-widget"' in content, "License status widget #license-status-widget is required!"
    assert "licenseTier" in content, "License tier state is required!"
    assert "licenseQuota" in content, "License quota state is required!"

def test_tauri_hardware_id_and_spooler_wiring():
    """Gate 3-B3 & Gate 4-1: Verifies that App.tsx wires native Tauri spooler and hardware GUID probe."""
    app_path = Path("apps/shopkeeper-web/src/App.tsx")
    content = app_path.read_text(encoding="utf-8")
    assert "trigger_direct_spooler_print" in content, "Tauri native spooler command must be wired!"
    assert "get_machine_hardware_id" in content, "Tauri native hardware GUID probe must be wired!"

def test_field_setup_checklist_exists():
    """Gate 8-4: Verifies existence of written 10-minute field onboarding SOP."""
    sop_path = Path("apps/shopkeeper-web/docs/FIELD_SETUP_CHECKLIST.md")
    assert sop_path.exists(), "FIELD_SETUP_CHECKLIST.md must exist!"
    content = sop_path.read_text(encoding="utf-8")
    assert "10-Minute Field Setup Checklist" in content
    assert "Toner cemetery Slide Demo" in content
    assert "Day-5 Conversion Follow-Up SOP" in content

def test_tauri_conf_port_and_updater():
    """Gate 8-1 & Gate 8-2: Verifies Tauri configuration targets POS port 5174 and configures updater."""
    conf_path = Path("apps/shopkeeper-desktop/src-tauri/tauri.conf.json")
    assert conf_path.exists(), "tauri.conf.json is missing!"
    data = json.loads(conf_path.read_text(encoding="utf-8"))
    assert data["build"]["devUrl"] == "http://localhost:5174", "devUrl must target dedicated POS port 5174!"
    assert data["plugins"]["updater"]["active"] is True, "Tauri auto-updater plugin must be active!"
