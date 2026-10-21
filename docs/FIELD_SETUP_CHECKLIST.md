# CleanNotes PrintFlow POS — 10-Minute Field Setup Checklist
## Counter Operator Onboarding SOP for Indian Commercial Xerox Shops
**Target Audience:** Field Engineers, Sales Reps, Shopkeeper Staff  
**Hardware Baseline:** Windows 10/11 Counter PC (4GB RAM minimum), Laser Printer (Canon iR / HP LaserJet)

---

## Pre-Flight Check (Minute 0–2)
1. **Physical Counter Space:** Identify counter monitor position next to main laser printer spooler.
2. **Network Connection:** Connect to shop Wi-Fi or USB tethering (requires 2G/3G minimum for periodic license heartbeat).
3. **Printer Status:** Confirm default Windows printer is set to the primary laser duplicator (e.g., Canon iR 2525 / HP LaserJet Pro).

---

## Installation & Launch (Minute 3–5)
1. **Launch Terminal:**
   - Double-click `CleanNotes-PrintFlow-POS.exe` or open `http://localhost:5174` (or `https://pos.cleannotes.app`).
2. **Hardware Fingerprint Authorization:**
   - The terminal automatically queries Windows Machine UUID (`csproduct get UUID`).
   - Counter status immediately shows: `[TRIAL • 7d Left • 50/day]`.
   - Zero registration friction — no credit card, no OTP, no complex login form.

---

## Live Counter Demo to Shop Owner (Minute 6–8)
1. **Toner cemetery Slide Demo:**
   - Ask the shopkeeper for their most toner-draining customer PDF (e.g. pitch-black lecture slides from PhysicsWallah or KD Campus).
   - Drag & drop the PDF into the 65% dropzone target (or press `Ctrl+V` to paste).
2. **One-Tap Whitening & Compression:**
   - Hit `[ Space ]` to process.
   - Show the shop owner the live progress bar: 97ms/page speed.
   - Point to the **Toner Cash Saved** counter: `+₹162.00 saved on this single job!`.
3. **Print Test & Thermal Receipt:**
   - Press `[ R ]` to open the 78mm Thermal Receipt modal.
   - Click `Print Thermal Slip` to print the customer voucher with toner arbitrage proof.
   - Point out: *"Show this slip to students so they know you whiten their notes cleanly without wasting ink."*

---

## Operator Training (Minute 9–10)
Teach the counter staff the 4 essential single-key hotkeys:
- **`[ Space ]`**: Process all queued PDFs and merge for print.
- **`[ Ctrl + P ]`**: Direct silent dispatch to the laser spooler.
- **`[ R ]`**: Print 78mm customer thermal savings receipt.
- **`[ Esc ]`**: Clear queue for the next walk-in customer.

---

## Day-5 Conversion Follow-Up SOP
On Day 5 of the 7-day trial:
1. Operator sees amber warning on license widget: `[TRIAL • 2d Left]`.
2. Click the widget or press `[ U ]` to display the Razorpay UPI Autopay QR code.
3. Shopkeeper scans with PhonePe / Google Pay / Paytm (₹499/mo mandate under RBI ₹15,000 threshold = 0 OTP friction).
4. Terminal flips instantly to `[PRO • 30d Left • 5000/day]`.
