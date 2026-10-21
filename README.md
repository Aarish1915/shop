# CleanNotes PrintFlow POS (B2B Xerox Counter Suite)

> **High-speed, offline-first slide background inverter and counter POS terminal for commercial Indian print & photocopy shops.**

[![Shopkeeper Quality Gate](https://github.com/Aarish1915/shop/actions/workflows/ci.yml/badge.svg)](https://github.com/Aarish1915/shop/actions)
[![License: Proprietary](https://img.shields.io/badge/License-Commercial-blue.svg)](#)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python&logoColor=white)](#)
[![React 19](https://img.shields.io/badge/React-19.0-61DAFB.svg?logo=react&logoColor=black)](#)
[![Vite](https://img.shields.io/badge/Vite-6.0-646CFF.svg?logo=vite&logoColor=white)](#)

---

## 💡 The Problem: The "Dark Slide" Cash Loss

Indian Xerox shops charge students **₹0.70 to ₹0.80 per page**. 
- On a normal white document (5% text coverage), raw toner costs **~5 paise (₹0.05)**.
- But on dark coaching/lecture slides (65% black coverage), toner consumption explodes **13× to ₹0.62 per page**!
- Adding A4 paper (₹0.48) + toner (₹0.62) + drum wear (₹0.08) = **₹1.18 cost per sheet**.
- **Shopkeepers lose ~43 paise out of their own pocket on every single dark slide!**

### The Solution:
CleanNotes PrintFlow whitens dark backgrounds to pure `#ffffff` paper while shielding human photos, diagrams, and color text.
- Drops toner coverage from 65% back to **4.2%**.
- **Saves ~₹0.58 in raw toner powder on every single page.**
- Pays for the ₹499/month subscription in just **2 to 3 days of walk-in student jobs**.

---

## 🚀 Quick Start (Local Development)

### 1. Start the B2B Backend Server
```bash
cd server
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

### 2. Start the Counter Web POS
```bash
npm install
npm run dev
```
Open **`http://localhost:5174`** in your browser.

### 3. Central Monitoring & Admin Center
Navigate to **`http://localhost:8001/admin`** to view live counter telemetry, active trial shops, churn alerts, and 1-tap WhatsApp nudge actions.

### 4. Marketing Landing Page
Visit **`http://localhost:8001/landing`** to view the interactive commercial toner savings calculator.

---

## 🧪 Testing Suite (40/40 Passing)

Run the comprehensive test harness including load tests, TTFB performance budgets, security headers, and Playwright E2E:
```bash
python -m pytest tests/ -v
```

---

## 📦 Deployment

- **Vercel (Frontend & PWA):** Simply connect this repository to Vercel. `vercel.json` is pre-configured.
- **Google Cloud Run (Backend API):**
  ```bash
  chmod +x deploy/deploy_cloudrun.sh
  ./deploy/deploy_cloudrun.sh
  ```
- **Windows Desktop (.exe):** Native silent print spooler powered by Tauri Rust in `apps/shopkeeper-desktop`.

---

## 🔒 Security & Compliance
- Hardware-bound machine fingerprinting (`csproduct UUID` on Windows).
- Dynamic CORS locked to production origins.
- 120 req/min sliding-window IP rate limiting.
- `X-Correlation-ID` tracing across every request.
- `pip-audit` automated dependency vulnerability scanning in CI.
