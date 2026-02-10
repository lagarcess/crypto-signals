"""
Strategy Synchronization Pipeline (SCD Type 2).

This pipeline syncs strategy configurations from Firestore (dim_strategies)
to BigQuery (dim_strategies), maintaining a full history of changes (SCD Type 2).
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery
from loguru import logger

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import StagingStrategy
from crypto_signals.pipelines.base import BigQueryPipelineBase
from crypto_signals.repository.firestore import StrategyRepository


class StrategySyncPipeline(BigQueryPipelineBase):
    """
    SCD Type 2 Pipeline for Strategy Configuration.

    Detects changes in Firestore strategy config and creates versioned
    records in BigQuery.
    """

    # Config fields tracked for change detection
    RELEVANT_CONFIG_KEYS = [
        "active",
        "timeframe",
        "asset_class",
        "assets",
        "risk_params",
        "confluence_config",
        "pattern_overrides",
    ]

    def __init__(self, full_extraction: bool = False):
        super().__init__(
            job_name="strategy_sync",
            staging_table_id=f"{get_settings().GOOGLE_CLOUD_PROJECT}.crypto_analytics.stg_strategies_import",
            fact_table_id=f"{get_settings().GOOGLE_CLOUD_PROJECT}.crypto_analytics.dim_strategies",
            id_column="strategy_id",  # Not strictly used in custom merge
            partition_column="valid_from",  # Used for partitioning if applicable
            schema_model=StagingStrategy,
        )
        self.repository = StrategyRepository()
        self.full_extraction = full_extraction

    def _calculate_hash(self, config_data: Dict[str, Any]) -> str:
        """Calculate a deterministic hash of the configuration."""
        subset = {k: config_data.get(k) for k in self.RELEVANT_CONFIG_KEYS}

        # Sort keys for deterministic JSON serialization
        serialized = json.dumps(subset, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _get_last_sync_time(self) -> datetime:
        """
        Fetch the high watermark (MAX(valid_from)) from BigQuery.
        Returns: datetime of the last successful sync.
        """
        if not self._check_table_exists(self.fact_table_id):
            logger.warning(
                f"Target table {self.fact_table_id} does not exist. Defaulting to Epoch."
            )
            return datetime(1970, 1, 1, tzinfo=timezone.utc)

        query = f"SELECT MAX(valid_from) as last_sync FROM `{self.fact_table_id}`"
        try:
            results = self.bq_client.query(query).result()
            for row in results:
                return row.last_sync or datetime(1970, 1, 1, tzinfo=timezone.utc)
        except Exception as e:
            logger.warning(f"Failed to fetch last sync time: {e}. Defaulting to Epoch.")

        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    def _get_bq_current_state(
        self, strategy_ids: Optional[List[str]] = None
    ) -> Dict[str, str]:
        """
        Fetch the current active version hash for strategies from BigQuery.

        Args:
            strategy_ids: Optional list of IDs to filter by.
                         If None, fetches all current records (full extraction).

        Returns: Dict[strategy_id, config_hash]
        """
        if not self._check_table_exists(self.fact_table_id):
            logger.warning(
                f"Target table {self.fact_table_id} does not exist. Assuming empty state."
            )
            return {}

        query = f"""
            SELECT strategy_id, config_hash
            FROM `{self.fact_table_id}`
            WHERE valid_to IS NULL
        """

        job_config = None
        if strategy_ids:
            # Safe parameterized query using UNNEST to handle a list of IDs
            query += " AND strategy_id IN UNNEST(@strategy_ids)"
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("strategy_ids", "STRING", strategy_ids)
                ]
            )

        try:
            results = self.bq_client.query(query, job_config=job_config).result()
            return {row.strategy_id: row.config_hash for row in results}
        except Exception as e:
            logger.warning(f"Failed to fetch BQ state: {e}. Assuming empty state.")
            return {}

    def extract(self) -> List[Dict[str, Any]]:
        """
        Extract strategies from Firestore and determine changes.
        """
        if self.full_extraction:
            logger.info("Extracting ALL strategies from Firestore (Full Sync)...")
            strategies = self.repository.get_all_strategies()
        else:
            last_sync = self._get_last_sync_time()
            logger.info(
                f"Extracting modified strategies since {last_sync} (Incremental Sync)..."
            )
            strategies = self.repository.get_modified_strategies(since=last_sync)

        if not strategies:
            logger.info("No strategies found in Firestore.")
            return []

        # Optimization: Fetch BQ state only for the strategies we retrieved from Firestore
        strategy_ids = [s.strategy_id for s in strategies]
        bq_state = self._get_bq_current_state(
            strategy_ids if not self.full_extraction else None
        )

        new_versions = []
        now = datetime.now(timezone.utc)

        for strategy in strategies:
            try:
                # Convert Pydantic model to dict for processing
                data = strategy.model_dump(mode="python")

                # Calculate Hash
                config_hash = self._calculate_hash(data)

                strategy_id = strategy.strategy_id
                current_hash = bq_state.get(strategy_id)

                if current_hash != config_hash:
                    logger.info(
                        f"Change detected for {strategy_id}. New Hash: {config_hash[:8]}"
                    )

                    # Validate required 'active' field explicitly
                    if "active" not in data:
                        logger.error(
                            f"Strategy {strategy_id} missing required 'active' field"
                        )
                        continue

                    # Create Staging Record
                    staging_record = {
                        "strategy_id": strategy_id,
                        "active": data["active"],
                        "timeframe": data.get("timeframe", ""),
                        "asset_class": data.get("asset_class", "CRYPTO"),
                        "assets": data.get("assets", []),
                        "risk_params": json.dumps(
                            data.get("risk_params", {}), sort_keys=True, default=str
                        ),
                        "confluence_config": json.dumps(
                            data.get("confluence_config", {}), sort_keys=True, default=str
                        ),
                        "pattern_overrides": json.dumps(
                            data.get("pattern_overrides", {}), sort_keys=True, default=str
                        ),
                        "config_hash": config_hash,
                        "valid_from": now,
                        "valid_to": None,
                        "is_current": True,
                    }
                    new_versions.append(staging_record)
                else:
                    logger.debug(f"No change for {strategy_id}")

            except Exception as e:
                logger.error(f"Error processing strategy {strategy.strategy_id}: {e}")
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
            (strategy_id, active, timeframe, asset_class, assets, risk_params, confluence_config, pattern_overrides, config_hash, valid_from, valid_to, is_current)
            SELECT
                strategy_id, active, timeframe, asset_class, assets, risk_params, confluence_config, pattern_overrides, config_hash, valid_from, valid_to, is_current
            FROM `{self.staging_table_id}`
        """

        logger.info("Closing old versions...")
        self.bq_client.query(update_query).result()

        logger.info("Inserting new versions...")
        self.bq_client.query(insert_query).result()

        logger.info("SCD Type 2 Merge complete.")
