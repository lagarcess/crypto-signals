---
description: Infrastructure health check (GCP, Firestore, Alpaca)
---

All diagnostic reports are written to `temp/reports/` (gitignored).

1. **GCP Health Check**
   // turbo
   - Check Cloud Run services: `gcloud run services list --platform managed` (verify active status).
   - Check recent error logs: `gcloud logging read "severity>=ERROR AND resource.type=cloud_run_revision" --limit 5`

2. **Alpaca Account Status**
   // turbo
   - Run account status check: `poetry run python -m crypto_signals.scripts.diagnostics.account_status`
   - Output: `temp/reports/account_status.txt`
   - Verify account balance, buying power, open positions.

3. **Firestore State Analysis**
   // turbo
   - Run state analysis: `poetry run python -m crypto_signals.scripts.diagnostics.state_analysis`
   - Output: `temp/reports/state_analysis.txt`
   - Check OPEN positions, active signals, verify no zombies.

4. **Forensic Analysis (Order Gap Detection)**
   // turbo
   - Run forensic analysis: `poetry run python -m crypto_signals.scripts.diagnostics.forensic_analysis`
   - Cross-reference Firestore positions with Alpaca orders.
   - Identify exit order gaps (positions closed in DB but no sell order on Alpaca).
   - Report orphaned positions and missing sell orders.

5. **Health Check (Connectivity)**
   // turbo
   - Run health check: `poetry run python -m crypto_signals.scripts.diagnostics.health_check`
   - Verify connectivity to Alpaca, Firestore, BigQuery, Discord.

6. **Report Summary**
   - Review all reports in `temp/reports/`
   - If critical issues found -> Suggest running `/fix` or creating GitHub issues.
   - If orphaned positions detected -> List symbols to manually close in Alpaca.
