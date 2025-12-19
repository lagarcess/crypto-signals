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
echo -n "your-discord-webhook-url" | gcloud secrets create DISCORD_WEBHOOK_URL --data-file=-
echo -n "$GCP_PROJECT" | gcloud secrets create GOOGLE_CLOUD_PROJECT --data-file=-
echo -n "true" | gcloud secrets create ALPACA_PAPER_TRADING --data-file=-
echo -n "false" | gcloud secrets create MOCK_DISCORD --data-file=-

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
    --set-secrets=ALPACA_API_KEY=ALPACA_API_KEY:latest,ALPACA_SECRET_KEY=ALPACA_SECRET_KEY:latest,DISCORD_WEBHOOK_URL=DISCORD_WEBHOOK_URL:latest,ALPACA_PAPER_TRADING=ALPACA_PAPER_TRADING:latest,MOCK_DISCORD=MOCK_DISCORD:latest

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

# Create cleanup job (runs daily at 2 AM UTC)
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

gcloud scheduler jobs create http crypto-signals-cleanup-daily \
    --location=us-central1 \
    --schedule="0 2 * * *" \
    --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT/jobs/crypto-signals-cleanup:run" \
    --http-method=POST \
    --oauth-service-account-email=$GCP_PROJECT@appspot.gserviceaccount.com
```

### 5. Configure Firestore

```bash
# Enable Firestore API
gcloud services enable firestore.googleapis.com

# Create Firestore database (if not exists)
gcloud firestore databases create --region=us-central1

# Create index for cleanup queries (if needed)
gcloud firestore indexes composite create \
    --collection-group=live_signals \
    --field-config field-path=expiration_at,order=ASCENDING \
    --field-config field-path=status,order=ASCENDING
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
    --set-secrets=ALPACA_API_KEY=ALPACA_API_KEY:latest,ALPACA_SECRET_KEY=ALPACA_SECRET_KEY:latest,DISCORD_WEBHOOK_URL=DISCORD_WEBHOOK_URL:latest,MOCK_DISCORD=MOCK_DISCORD:latest

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
DISCORD_WEBHOOK_URL=your-webhook-url
ALPACA_PAPER_TRADING=true
MOCK_DISCORD=true
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
