"""
Base Pipeline Module.

This module provides the `BigQueryPipelineBase` class, which serves as the
Execution Engine for all data movement from Firestore (Operational) to
BigQuery (Analytical).

It implements the strict "Truncate -> Load (Staging) -> Merge (Fact)" pattern
to ensure idempotency and data consistency.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, List, Type

from google.cloud import bigquery
from pydantic import BaseModel

from crypto_signals.config import settings

# Configure logging
logger = logging.getLogger(__name__)


class BigQueryPipelineBase(ABC):
    """
    Abstract base class for Firestore-to-BigQuery pipelines.

    This class implements the "Heavy" pattern where the base class handles
    the complexity of BigQuery interactions (Truncate, Load, Merge), and
    subclasses focus on configuration and data extraction.

    Attributes:
        job_name: Human-readable name for logging (e.g. "trade_archival")
        staging_table_id: Full BigQuery ID for staging (project.dataset.table)
        fact_table_id: Full BigQuery ID for fact/target (project.dataset.table)
        id_column: Primary key column name for the MERGE join
        partition_column: Partition column name for the MERGE join
        schema_model: Pydantic model class for validation and schema definition
    """

    def __init__(
        self,
        job_name: str,
        staging_table_id: str,
        fact_table_id: str,
        id_column: str,
        partition_column: str,
        schema_model: Type[BaseModel],
    ):
        """Initialize the pipeline with configuration and BigQuery client."""
        self.job_name = job_name
        self.staging_table_id = staging_table_id
        self.fact_table_id = fact_table_id
        self.id_column = id_column
        self.partition_column = partition_column
        self.schema_model = schema_model

        # Initialize BigQuery Client
        # We use the project from settings to ensure we target the right GCP env
        self.bq_client = bigquery.Client(project=settings().GOOGLE_CLOUD_PROJECT)

    @abstractmethod
    def extract(self) -> List[Any]:
        """
        Extract data from the source (e.g., Firestore).

        Returns:
            List of raw data objects (dicts or model instances).
        """

    @abstractmethod
    def cleanup(self, data: List[BaseModel]) -> None:
        """
        Delete processed records from the source system.

        Args:
            data: The list of validated Pydantic models that were successfully merged.
        """

    def transform(self, raw_data: List[Any]) -> List[dict]:
        """
        Validate and transform raw data using the Pydantic schema.

        CRITICAL: Uses mode='json' to ensure dates/datetimes are serialized
        to ISO strings, which `client.insert_rows_json` requires.

        Args:
            raw_data: List of raw input data.

        Returns:
            List of dictionaries ready for BigQuery insertion.
        """
        logger.info(f"[{self.job_name}] Transforming {len(raw_data)} records...")
        transformed = []
        for item in raw_data:
            if isinstance(item, dict):
                model = self.schema_model.model_validate(item)
            else:
                model = self.schema_model.model_validate(item)

            # Dump to JSON-compatible dict (handling dates/UUIDs)
            transformed.append(model.model_dump(mode="json"))

        return transformed

    def _truncate_staging(self) -> None:
        """Truncate the staging table to clear old data."""
        query = f"TRUNCATE TABLE `{self.staging_table_id}`"
        logger.info(
            f"[{self.job_name}] Truncating staging table: {self.staging_table_id}"
        )
        query_job = self.bq_client.query(query)
        query_job.result()  # Wait for job to complete

    def _load_to_staging(self, data: List[dict]) -> None:
        """
        Load transformed data into the staging table.

        Args:
            data: List of dicts to insert.
        """
        if not data:
            logger.warning(f"[{self.job_name}] No data to load to staging.")
            return

        logger.info(
            f"[{self.job_name}] Loading {len(data)} rows to {self.staging_table_id}..."
        )

        # insert_rows_json handles batching automatically
        errors = self.bq_client.insert_rows_json(self.staging_table_id, data)

        if errors:
            error_msg = f"[{self.job_name}] Failed to insert rows to staging: {errors}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _execute_merge(self) -> None:
        """
        Execute the MERGE statement to upsert data from Staging to Fact.

        Dynamically constructs the SQL based on the Pydantic model fields.
        """
        logger.info(f"[{self.job_name}] Executing MERGE operation...")

        # 1. Get all column names from the model
        columns = list(self.schema_model.model_fields.keys())

        # 2. Build UPDATE clause (T.col = S.col)
        # We generally update ALL columns on match to ensure consistency
        update_list = []
        for col in columns:
            # Skip updating join keys (usually harmless if they match)
            if col not in [self.id_column, self.partition_column]:
                update_list.append(f"T.{col} = S.{col}")

        update_clause = ", ".join(update_list)

        # 3. Build INSERT clause
        insert_cols = ", ".join(columns)
        insert_vals = ", ".join([f"S.{col}" for col in columns])

        # 4. Construct the full MERGE query
        # Using `T` for Target (Fact) and `S` for Source (Staging)
        query = f"""
            MERGE `{self.fact_table_id}` T
            USING `{self.staging_table_id}` S
            ON T.{self.id_column} = S.{self.id_column}
            AND T.{self.partition_column} = S.{self.partition_column}
            WHEN MATCHED THEN
                UPDATE SET {update_clause}
            WHEN NOT MATCHED THEN
                INSERT ({insert_cols})
                VALUES ({insert_vals})
        """

        # Execute the merge
        query_job = self.bq_client.query(query)
        query_job.result()  # Wait for completion
        logger.info(f"[{self.job_name}] MERGE completed successfully.")

    def run(self) -> None:
        """
        Orchestrate the full pipeline execution.

        Flow: Extract -> Transform -> Truncate Staging -> Load Staging
              -> Merge -> Cleanup

        Raises:
            Exception: If any step fails, logs and RE-RAISES the exception.
                       Cleanup is NOT executed on failure.
        """
        logger.info(f"[{self.job_name}] Starting pipeline execution...")

        try:
            # 1. Extract
            raw_data = self.extract()
            if not raw_data:
                logger.info(f"[{self.job_name}] No data found. Exiting.")
                return

            # 2. Transform
            # Note: We need the Pydantic models for Cleanup later, but dicts for BQ
            # So we might validate twice or store both.
            # Optimization: self.transform returns dicts.
            # We reconstruct models for cleanup if needed, or extract returns models.
            # Let's assume extract returns models or dicts, and transform returns dicts.
            transformed_data = self.transform(raw_data)

            # 3. Truncate Staging
            self._truncate_staging()

            # 4. Load to Staging
            self._load_to_staging(transformed_data)

            # 5. Execute Merge
            self._execute_merge()

            # 6. Cleanup (Optional: passed validated models effectively)
            # Since raw_data might be dicts, we might want to pass the raw_data
            # or reconstruct models. Calling cleanup with raw_data for now
            # as the interface defines `data: List[BaseModel]`.
            # If raw_data matches the signature, great. If not, we should probably
            # pass the validated models.
            # Let's create a list of models for cleanup to ensure type safety.
            # We re-validate briefly or keep them from transform loop.
            # To avoid double validation overhead, let's simply assume
            # raw_data is sufficient for cleanup if it has IDs,
            # OR better: in transform loop we could allow returning a tuple.
            # But to keep it simple and abide by strict type hints:

            # Re-creating models for cleanup to ensure type safety if raw_data was dicts
            # This is cheap compared to BQ/Network ops.
            cleanup_models = [self.schema_model.model_validate(d) for d in raw_data]
            self.cleanup(cleanup_models)

            logger.info(f"[{self.job_name}] Pipeline finished successfully.")

        except Exception as e:
            logger.error(f"[{self.job_name}] Pipeline FAILED: {str(e)}", exc_info=True)
            # CRITICAL: Re-raise to ensure job failure is reported to Cloud Run
            raise
