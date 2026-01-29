"""
Strategy Synchronization Pipeline (SCD Type 2).

This pipeline syncs strategy configurations from Firestore (dim_strategies)
to BigQuery (dim_strategies), maintaining a full history of changes (SCD Type 2).
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from google.cloud import firestore
from loguru import logger

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import StagingStrategy
from crypto_signals.pipelines.base import BigQueryPipelineBase


class StrategySyncPipeline(BigQueryPipelineBase):
    """
    SCD Type 2 Pipeline for Strategy Configuration.

    Detects changes in Firestore strategy config and creates versioned
    records in BigQuery.
    """

    def __init__(self):
        super().__init__(
            job_name="strategy_sync",
            staging_table_id=f"{get_settings().GOOGLE_CLOUD_PROJECT}.crypto_signals.stg_strategies_import",
            fact_table_id=f"{get_settings().GOOGLE_CLOUD_PROJECT}.crypto_signals.dim_strategies",
            id_column="strategy_id",  # Not strictly used in custom merge
            partition_column="valid_from",  # Used for partitioning if applicable
            schema_model=StagingStrategy,
        )
        self.firestore_client = firestore.Client(project=get_settings().GOOGLE_CLOUD_PROJECT)

    def _calculate_hash(self, config_data: Dict[str, Any]) -> str:
        """Calculate a deterministic hash of the configuration."""
        # Relevant fields for change detection
        relevant_keys = ["active", "timeframe", "asset_class", "assets", "risk_params"]
        subset = {k: config_data.get(k) for k in relevant_keys}

        # Sort keys for deterministic JSON serialization
        serialized = json.dumps(subset, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _get_bq_current_state(self) -> Dict[str, str]:
        """
        Fetch the current active version hash for each strategy from BigQuery.
        Returns: Dict[strategy_id, config_hash]
        """
        if not self._check_table_exists(self.fact_table_id):
            logger.warning(f"Target table {self.fact_table_id} does not exist. Assuming empty state.")
            return {}

        query = f"""
            SELECT strategy_id, config_hash
            FROM `{self.fact_table_id}`
            WHERE valid_to IS NULL
        """
        try:
            results = self.bq_client.query(query).result()
            return {row.strategy_id: row.config_hash for row in results}
        except Exception as e:
            logger.warning(f"Failed to fetch BQ state: {e}. Assuming empty state.")
            return {}

    def extract(self) -> List[Dict[str, Any]]:
        """
        Extract strategies from Firestore and determine changes.
        """
        logger.info("Extracting strategies from Firestore...")
        collection_ref = self.firestore_client.collection("dim_strategies")
        docs = list(collection_ref.stream())

        if not docs:
            logger.info("No strategies found in Firestore.")
            return []

        # Get current state from BQ
        bq_state = self._get_bq_current_state()

        new_versions = []
        now = datetime.now(timezone.utc)

        for doc in docs:
            data = doc.to_dict()
            try:
                # Add ID if missing (use doc.id)
                if "strategy_id" not in data:
                    data["strategy_id"] = doc.id

                # Calculate Hash
                config_hash = self._calculate_hash(data)

                strategy_id = data["strategy_id"]
                current_hash = bq_state.get(strategy_id)

                if current_hash != config_hash:
                    logger.info(f"Change detected for {strategy_id}. New Hash: {config_hash[:8]}")

                    # Create Staging Record
                    staging_record = {
                        "strategy_id": strategy_id,
                        "active": data.get("active", False),
                        "timeframe": data.get("timeframe", ""),
                        "asset_class": data.get("asset_class", "CRYPTO"),
                        "assets": data.get("assets", []),
                        "risk_params": json.dumps(
                            data.get("risk_params", {}), sort_keys=True, default=str
                        ),
                        "config_hash": config_hash,
                        "valid_from": now,
                        "valid_to": None,
                        "is_current": True
                    }
                    new_versions.append(staging_record)
                else:
                    logger.debug(f"No change for {strategy_id}")

            except Exception as e:
                logger.error(f"Error processing strategy {doc.id}: {e}")
                continue

        logger.info(f"Found {len(new_versions)} strategy updates.")
        return new_versions

    def cleanup(self, data: List[Any]) -> None:
        """No-op for strategy sync (we don't delete source)."""
        pass

    def _execute_merge(self) -> None:
        """
        Execute SCD Type 2 Merge.
        1. Close old records (Update valid_to)
        2. Insert new records
        """
        if not self._check_table_exists(self.fact_table_id):
             # If table missing, we should probably fail or handle it.
             # Base class raises error if fact table missing in `_execute_merge`.
             pass

        logger.info(f"[{self.job_name}] Executing SCD Type 2 Merge...")

        # 1. Update existing current records that have a new version in staging
        # We join Staging on strategy_id.
        update_query = f"""
            UPDATE `{self.fact_table_id}` T
            SET
                valid_to = S.valid_from,
                is_current = FALSE
            FROM `{self.staging_table_id}` S
            WHERE T.strategy_id = S.strategy_id
              AND T.valid_to IS NULL
        """

        # 2. Insert new records
        insert_query = f"""
            INSERT INTO `{self.fact_table_id}`
            (strategy_id, active, timeframe, asset_class, assets, risk_params, config_hash, valid_from, valid_to, is_current)
            SELECT
                strategy_id, active, timeframe, asset_class, assets, risk_params, config_hash, valid_from, valid_to, is_current
            FROM `{self.staging_table_id}`
        """

        logger.info("Closing old versions...")
        self.bq_client.query(update_query).result()

        logger.info("Inserting new versions...")
        self.bq_client.query(insert_query).result()

        logger.info("SCD Type 2 Merge complete.")
