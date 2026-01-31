#!/bin/bash
# Configure BigQuery Dataset Default Partition Expiration (Layer 2 Safety Net)

PROJECT_ID=${GOOGLE_CLOUD_PROJECT}
if [ -z "$PROJECT_ID" ]; then
  echo "Error: GOOGLE_CLOUD_PROJECT environment variable is not set."
  exit 1
fi

DATASETS=("crypto_analytics" "crypto_analytics_test")
EXPIRATION_SECONDS=$((7 * 24 * 60 * 60)) # 7 days

for DATASET in "${DATASETS[@]}"; do
  echo "Configuring TTL for ${PROJECT_ID}:${DATASET}..."
  bq update --default_partition_expiration ${EXPIRATION_SECONDS} ${PROJECT_ID}:${DATASET} || echo "Dataset ${DATASET} not found or update failed."
done
