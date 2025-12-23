# Crypto Sentinel - Cloud Deployment Guide

## Overview

This guide provides comprehensive instructions for deploying Crypto Sentinel to Google Cloud Platform (GCP) with production-ready configurations.

## Prerequisites

1. **GCP Account** with appropriate permissions:
   - Cloud Run Admin
   - Secret Manager Admin
   - Firestore User
   - BigQuery Admin
   - Artifact Registry Writer

2. **Local Tools**:
   - Docker
   - gcloud CLI
   - git

3. **API Credentials**:
   - Alpaca API Key and Secret
   - Discord Webhook URL

## Setup Instructions

### 1. Configure Google Secret Manager

Store all sensitive credentials in Secret Manager before deployment:

```bash
# Set your project ID
export GCP_PROJECT="your-project-id"
gcloud config set project $GCP_PROJECT

# Create secrets in Secret Manager
echo -n "your-alpaca-api-key" | gcloud secrets create ALPACA_API_KEY --data-file=-
echo -n "your-alpaca-secret-key" | gcloud secrets create ALPACA_SECRET_KEY --data-file=-
echo -n "$GCP_PROJECT" | gcloud secrets create GOOGLE_CLOUD_PROJECT --data-file=-
echo -n "true" | gcloud secrets create ALPACA_PAPER_TRADING --data-file=-

# Discord Webhooks (Multi-destination Routing)
echo -n "your-test-discord-webhook" | gcloud secrets create TEST_DISCORD_WEBHOOK --data-file=-
echo -n "true" | gcloud secrets create TEST_MODE --data-file=-  # Set to 'false' for production

# Production webhooks (required when TEST_MODE=false)
# echo -n "your-crypto-discord-webhook" | gcloud secrets create LIVE_CRYPTO_DISCORD_WEBHOOK_URL --data-file=-
# echo -n "your-stock-discord-webhook" | gcloud secrets create LIVE_STOCK_DISCORD_WEBHOOK_URL --data-file=-

# Verify secrets
gcloud secrets list
```

### 2. Build and Push Docker Image

```bash
# Enable required APIs
gcloud services enable artifactregistry.googleapis.com
gcloud services enable run.googleapis.com

# Create Artifact Registry repository
gcloud artifacts repositories create crypto-signals \
    --repository-format=docker \
    --location=us-central1 \
    --description="Crypto Sentinel Docker images"

# Configure Docker authentication
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build the image
docker build -t crypto-signals:latest .

# Tag for Artifact Registry
docker tag crypto-signals:latest \
    us-central1-docker.pkg.dev/$GCP_PROJECT/crypto-signals/crypto-signals:latest

# Push to Artifact Registry
docker push us-central1-docker.pkg.dev/$GCP_PROJECT/crypto-signals/crypto-signals:latest
```

### 3. Deploy to Cloud Run (Scheduled Job)

```bash
# Create Cloud Run Job
gcloud run jobs create crypto-signals-job \
    --image=us-central1-docker.pkg.dev/$GCP_PROJECT/crypto-signals/crypto-signals:latest \
    --region=us-central1 \
    --max-retries=1 \
    --task-timeout=10m \
    --memory=1Gi \
    --cpu=1 \
    --set-env-vars=GOOGLE_CLOUD_PROJECT=$GCP_PROJECT \
    --set-secrets=ALPACA_API_KEY=ALPACA_API_KEY:latest,ALPACA_SECRET_KEY=ALPACA_SECRET_KEY:latest,TEST_DISCORD_WEBHOOK=TEST_DISCORD_WEBHOOK:latest,TEST_MODE=TEST_MODE:latest,ALPACA_PAPER_TRADING=ALPACA_PAPER_TRADING:latest

# For production with separate crypto/stock webhooks, add:
# --set-secrets=...,LIVE_CRYPTO_DISCORD_WEBHOOK_URL=LIVE_CRYPTO_DISCORD_WEBHOOK_URL:latest,LIVE_STOCK_DISCORD_WEBHOOK_URL=LIVE_STOCK_DISCORD_WEBHOOK_URL:latest

# Test the job manually
gcloud run jobs execute crypto-signals-job --region=us-central1
```

### 4. Schedule with Cloud Scheduler

```bash
# Enable Cloud Scheduler API
gcloud services enable cloudscheduler.googleapis.com

# Create scheduler job (runs daily at 9 AM UTC)
gcloud scheduler jobs create http crypto-signals-daily \
    --location=us-central1 \
    --schedule="0 9 * * *" \
    --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT/jobs/crypto-signals-job:run" \
    --http-method=POST \
    --oauth-service-account-email=$GCP_PROJECT@appspot.gserviceaccount.com
```

### 5. Configure Firestore

```bash
# Enable Firestore API
gcloud services enable firestore.googleapis.com

# Create Firestore database (if not exists)
gcloud firestore databases create --region=us-central1
```

**Configure Automatic TTL (Recommended):**

The application stores signals with an `expireAt` timestamp field. To enable Google's automatic TTL deletion:

1. Go to [Firestore Console](https://console.cloud.google.com/firestore)
2. Select your database
3. Click on "Time-to-live" in the left menu
4. Click "Create TTL policy"
5. Configure:
   - Collection ID: `live_signals`
   - Timestamp field: `expireAt`
6. Click "Create"

With automatic TTL enabled, Google will delete expired documents at no extra cost, eliminating the need to run the `cleanup_firestore.py` script.

**Alternative: Manual Cleanup**

If you prefer manual control, skip the TTL policy and schedule the cleanup job:

```bash
# Create cleanup job
gcloud run jobs create crypto-signals-cleanup \
    --image=us-central1-docker.pkg.dev/$GCP_PROJECT/crypto-signals/crypto-signals:latest \
    --region=us-central1 \
    --command="python,-m,crypto_signals.scripts.cleanup_firestore" \
    --max-retries=1 \
    --task-timeout=5m \
    --memory=512Mi \
    --cpu=0.5 \
    --set-env-vars=GOOGLE_CLOUD_PROJECT=$GCP_PROJECT \
    --set-secrets=ALPACA_API_KEY=ALPACA_API_KEY:latest,ALPACA_SECRET_KEY=ALPACA_SECRET_KEY:latest

# Schedule cleanup (daily at 2 AM UTC)
gcloud scheduler jobs create http crypto-signals-cleanup-daily \
    --location=us-central1 \
    --schedule="0 2 * * *" \
    --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT/jobs/crypto-signals-cleanup:run" \
    --http-method=POST \
    --oauth-service-account-email=$GCP_PROJECT@appspot.gserviceaccount.com
```

**Note:** If you have an existing index for cleanup queries, you can remove it after enabling automatic TTL:

```bash
# List indexes (find the cleanup index ID)
gcloud firestore indexes composite list

# Delete the index (optional, after TTL is enabled)
gcloud firestore indexes composite delete INDEX_ID
```

### 6. Health Check Setup

```bash
# Create health check job
gcloud run jobs create crypto-signals-healthcheck \
    --image=us-central1-docker.pkg.dev/$GCP_PROJECT/crypto-signals/crypto-signals:latest \
    --region=us-central1 \
    --command="python,-m,crypto_signals.scripts.health_check" \
    --max-retries=0 \
    --task-timeout=2m \
    --memory=256Mi \
    --cpu=0.5 \
    --set-env-vars=GOOGLE_CLOUD_PROJECT=$GCP_PROJECT \
    --set-secrets=ALPACA_API_KEY=ALPACA_API_KEY:latest,ALPACA_SECRET_KEY=ALPACA_SECRET_KEY:latest,TEST_DISCORD_WEBHOOK=TEST_DISCORD_WEBHOOK:latest,TEST_MODE=TEST_MODE:latest

# Test health check
gcloud run jobs execute crypto-signals-healthcheck --region=us-central1
```

## Local Development

For local testing with Docker:

```bash
# Create secrets directory
mkdir -p secrets

# Add your GCP service account key
cp /path/to/your-service-account-key.json secrets/gcp-key.json

# Create .env file
cat > .env << EOF
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=./secrets/gcp-key.json
ALPACA_API_KEY=your-key
ALPACA_SECRET_KEY=your-secret
TEST_DISCORD_WEBHOOK=your-test-webhook-url
TEST_MODE=true
ALPACA_PAPER_TRADING=true
DISABLE_SECRET_MANAGER=true
EOF

# Run with Docker Compose
docker-compose up

# Or run health check
docker-compose --profile healthcheck run healthcheck
```

## Monitoring and Observability

### View Logs

```bash
# View job execution logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=crypto-signals-job" \
    --limit=50 \
    --format=json

# Follow logs in real-time
gcloud logging tail "resource.type=cloud_run_job AND resource.labels.job_name=crypto-signals-job"
```

### View Job Executions

```bash
# List recent executions
gcloud run jobs executions list \
    --job=crypto-signals-job \
    --region=us-central1 \
    --limit=10

# View execution details
gcloud run jobs executions describe EXECUTION_NAME \
    --region=us-central1
```

### Set Up Alerts

Create alerts in Cloud Monitoring for:
- Job failures (exit code != 0)
- Execution time > 5 minutes
- Memory usage > 80%
- API rate limit errors

## Security Best Practices

1. **Secret Management**:
   - Never commit secrets to git
   - Use Secret Manager for all credentials
   - Rotate secrets regularly

2. **IAM Permissions**:
   - Use least privilege principle
   - Create dedicated service account for Cloud Run
   - Grant only necessary permissions

3. **Network Security**:
   - Use VPC Service Controls if available
   - Enable VPC egress controls
   - Monitor outbound connections

4. **Container Security**:
   - Run as non-root user (already configured)
   - Keep base image updated
   - Scan images for vulnerabilities

## Cost Optimization

1. **Cloud Run**:
   - Use minimum CPU/memory needed
   - Set appropriate timeouts
   - Schedule jobs during off-peak hours

2. **Firestore**:
   - Enable TTL for automatic cleanup
   - Run cleanup job daily
   - Monitor document counts

3. **BigQuery**:
   - Use partitioned tables
   - Set expiration on staging tables
   - Monitor query costs

## Troubleshooting

### Job Fails to Start

```bash
# Check job configuration
gcloud run jobs describe crypto-signals-job --region=us-central1

# Check secret access
gcloud secrets versions access latest --secret=ALPACA_API_KEY

# Check service account permissions
gcloud projects get-iam-policy $GCP_PROJECT
```

### API Rate Limiting

If hitting Alpaca rate limits (200 req/min):

```bash
# Increase delay between symbols
gcloud run jobs update crypto-signals-job \
    --update-env-vars RATE_LIMIT_DELAY=1.0 \
    --region=us-central1

# Or reduce portfolio size in config
```

### Out of Memory

```bash
# Increase memory allocation
gcloud run jobs update crypto-signals-job \
    --memory=2Gi \
    --region=us-central1
```

## Rollback Procedure

```bash
# List previous revisions
gcloud artifacts docker images list \
    us-central1-docker.pkg.dev/$GCP_PROJECT/crypto-signals/crypto-signals

# Deploy previous image
gcloud run jobs update crypto-signals-job \
    --image=us-central1-docker.pkg.dev/$GCP_PROJECT/crypto-signals/crypto-signals:PREVIOUS_TAG \
    --region=us-central1
```

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Secret Manager Best Practices](https://cloud.google.com/secret-manager/docs/best-practices)
- [Firestore TTL Policies](https://cloud.google.com/firestore/docs/ttl)
- [Alpaca API Documentation](https://alpaca.markets/docs/)
