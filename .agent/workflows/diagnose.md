---
description: Infrastructure health check (GCP, Firestore, Alpaca)
---

1. **GCP Health Check**
   // turbo
   - Check Cloud Run services: `gcloud run services list --platform managed` (verify active status).
   - Check recent error logs: `gcloud logging read "severity>=ERROR AND resource.type=cloud_run_revision" --limit 5`

2. **Data Persistence Check**
   - Verify Firestore connection (via smoke test module).
   - Check for "Zombie" signals (status=WAITING but no discord_thread_id) in Firestore.

3. **Broker Health**
   - Check Alpaca Clock/Status (via API or smoke test).
   - Verify no "orphaned" positions (Open in Alpaca but Closed in DB).

4. **Report**
   - Output a "System Health Report".
   - If critical issues found -> Suggest running `/fix`.
