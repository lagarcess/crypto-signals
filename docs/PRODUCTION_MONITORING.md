# Production Monitoring & Data Management

**Last Updated:** December 26, 2025

This guide documents the monitoring, alerting, and data lifecycle configurations for Crypto Sentinel on GCP.

## Table of Contents

- [Overview](#overview)
- [1. Monitoring Alerts](#1-monitoring-alerts)
  - [1.1 Job Failure Alert](#11-job-failure-alert)
  - [1.2 High Memory Usage Alert](#12-high-memory-usage-alert)
  - [1.3 Execution Time Alert (Future)](#13-execution-time-alert-future)
- [2. Firestore TTL](#2-firestore-ttl)
- [3. Setup Commands Reference](#3-setup-commands-reference)

---

## Overview

**When to configure:** After your Cloud Run job is deployed and running successfully.

**Why it matters:**
- **Alerts** notify you immediately when something goes wrong, reducing downtime
- **Firestore TTL** automatically cleans up old data, reducing storage costs

---

## 1. Monitoring Alerts

### 1.1 Job Failure Alert

**Purpose:** Get notified immediately when the Cloud Run job fails with an error.

**Configuration:**
| Setting | Value |
|---------|-------|
| Type | Log-based alert |
| Filter | `resource.type="cloud_run_job" AND resource.labels.job_name="crypto-signals-job" AND severity>=ERROR` |
| Rate Limit | 5 minutes (prevents alert spam) |

**When to use:** Always enable this for production jobs.

**CLI Command:**
```powershell
gcloud alpha monitoring policies create --policy-from-file="docs/gcp-alerts/job-failure-alert.yaml"
```

---

### 1.2 High Memory Usage Alert

**Purpose:** Get warned when memory utilization exceeds 80% for more than 5 minutes.

**Configuration:**
| Setting | Value |
|---------|-------|
| Type | Metric-based alert |
| Metric | `run.googleapis.com/container/memory/utilization` |
| Threshold | > 80% |
| Duration | 5 minutes |
| Severity | WARNING |

**When to use:** Enable when running memory-intensive workloads to catch issues before they cause OOM crashes.

**Why 80%:** Gives you buffer time to react before hitting 100% and causing job failures.

---

### 1.3 Execution Time Alert (Future)

> [!NOTE]
> This alert was not created due to CLI limitations. Consider adding manually via Cloud Console when needed.

**Purpose:** Alert when job execution exceeds expected duration (e.g., 5 minutes).

**When to add:** If you notice jobs taking longer than expected or if API rate limits cause slow processing.

**YAML Template:** See `docs/gcp-alerts/execution-time-alert.yaml`

---

## 2. Firestore TTL

**Purpose:** Automatically delete old signal documents after 30 days, reducing storage costs without manual cleanup scripts.

**Configuration:**
| Setting | Value |
|---------|-------|
| Collection | `live_signals` |
| Timestamp Field | `expireAt` |
| State | ACTIVE |

**How it works:**
1. When creating a document, set the `expireAt` field to a timestamp 30 days in the future
2. Google automatically deletes documents when `expireAt` is in the past
3. Deletion happens within 72 hours of expiration (usually faster)

**CLI Command:**
```powershell
gcloud firestore fields ttls update expireAt --collection-group=live_signals --enable-ttl
```

**Verification:**
```powershell
gcloud firestore fields ttls list --collection-group=live_signals
```

> [!IMPORTANT]
> Your application code must set the `expireAt` field on documents for TTL to work. Example in Python:
> ```python
> from datetime import datetime, timedelta
>
> doc_data = {
>     "symbol": "BTC/USD",
>     "signal": "BUY",
>     "expireAt": datetime.utcnow() + timedelta(days=30)
> }
> ```

---

## 3. Setup Commands Reference

### Prerequisites

```powershell
# Ensure gcloud is in PATH
$env:Path = $env:Path + ";C:\Users\garce\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin"

# Set project
gcloud config set project crypto-signal-bot-481500

# Install alpha components (for monitoring commands)
gcloud components install alpha
```

### Enable Monitoring API

```powershell
gcloud services enable monitoring.googleapis.com
```

### Create Alert Policies

```powershell
# Job Failure Alert
gcloud alpha monitoring policies create --policy-from-file="docs/gcp-alerts/job-failure-alert.yaml"

# Memory Usage Alert (if not already created)
gcloud alpha monitoring policies create --policy-from-file="docs/gcp-alerts/memory-usage-alert.yaml"
```

### Enable Firestore TTL

```powershell
gcloud firestore fields ttls update expireAt --collection-group=live_signals --enable-ttl
```

### Verification Commands

```powershell
# List all alert policies
gcloud alpha monitoring policies list --format="table(displayName,enabled)"

# Check Firestore TTL status
gcloud firestore fields ttls list --collection-group=live_signals

# View recent job executions
gcloud run jobs executions list --job=crypto-signals-job --region=us-central1 --limit=5
```

---

## Related Documentation

- [GCP Deployment Guide](./GCP_DEPLOYMENT_GUIDE.md) - Initial infrastructure setup
- [Troubleshooting Guide](./TROUBLESHOOTING.md) - Common errors and solutions
- [Alert Policy YAML Files](./gcp-alerts/) - Source configuration files

---

**Status:**
- ✅ Job Failure Alert - Active
- ✅ High Memory Usage Alert - Active
- ⏳ Execution Time Alert - Not configured (optional)
- ✅ Firestore TTL - Active on `live_signals` collection
