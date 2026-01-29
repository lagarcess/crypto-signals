"""
Base Pipeline Module.

This module provides the `BigQueryPipelineBase` class, which serves as the
Execution Engine for all data movement from Firestore (Operational) to
BigQuery (Analytical).

It implements the strict "Truncate -> Load (Staging) -> Merge (Fact)" pattern
to ensure idempotency and data consistency.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type

from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from loguru import logger
from pydantic import BaseModel

from crypto_signals.config import get_settings
from crypto_signals.engine.schema_guardian import SchemaGuardian


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
        self.bq_client = bigquery.Client(project=get_settings().GOOGLE_CLOUD_PROJECT)

        # Initialize Schema Guardian (Strict Mode by default for now)
        # Initialize Schema Guardian
        # Note: V1 enforces Strict Mode everywhere.
        settings = get_settings()
        self.guardian = SchemaGuardian(
            self.bq_client, strict_mode=settings.SCHEMA_GUARDIAN_STRICT_MODE
        )

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

    def transform(self, raw_data: List[Any]) -> List[Dict[str, Any]]:
        """
        Validate and transform raw data using the Pydantic schema.

        Args:
            raw_data: List of raw input data.

        Returns:
            List of dictionaries ready for BigQuery insertion.
        """
        logger.info(f"[{self.job_name}] Transforming {len(raw_data)} records...")
        transformed = []
        for item in raw_data:
            model = self.schema_model.model_validate(item)
            transformed.append(model.model_dump(mode="json"))

        return transformed

    def _check_table_exists(self, table_id: str) -> bool:
        """Check if a BigQuery table exists."""
        try:
            self.bq_client.get_table(table_id)
            return True
        except NotFound:
            return False

    def _truncate_staging(self) -> None:
        """Truncate the staging table to clear old data."""
        if not self._check_table_exists(self.staging_table_id):
            logger.warning(
                f"[{self.job_name}] Staging table {self.staging_table_id} not found. Skipping truncate."
            )
            return

        query = f"TRUNCATE TABLE `{self.staging_table_id}`"
        logger.info(
            f"[{self.job_name}] Truncating staging table: {self.staging_table_id}"
        )
        query_job = self.bq_client.query(query)
        query_job.result()  # Wait for job to complete

    def _load_to_staging(self, data: List[Dict[str, Any]]) -> None:
        """
        Load transformed data into the staging table.

        Args:
            data: List of dicts to insert.
        """
        if not data:
            logger.warning(f"[{self.job_name}] No data to load to staging.")
            return

        if not self._check_table_exists(self.staging_table_id):
            logger.error(
                f"[{self.job_name}] Staging table {self.staging_table_id} not found. Cannot load data."
            )
            raise RuntimeError(f"Staging table {self.staging_table_id} not found")

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
        if not self._check_table_exists(self.fact_table_id):
            logger.error(
                f"[{self.job_name}] Fact table {self.fact_table_id} not found. Cannot merge."
            )
            raise RuntimeError(f"Fact table {self.fact_table_id} not found")

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

    def run(self) -> int:
        """
        Orchestrate the full pipeline execution.

        Flow: Validate Schema -> Extract -> Transform -> Truncate Staging -> Load Staging
              -> Merge -> Cleanup

        Returns:
            int: Number of records processed.

        Raises:
            Exception: If any step fails, logs and RE-RAISES the exception.
                       Cleanup is NOT executed on failure.
        """
        logger.info(f"[{self.job_name}] Starting pipeline execution...")

        try:
            # 0. Pre-flight Check: Validate Schema
            logger.info(f"[{self.job_name}] Validating BigQuery Schema...")
            # The guardian will raise an exception if strict_mode is True and there's a mismatch
            self.guardian.validate_schema(
                table_id=self.fact_table_id, model=self.schema_model
            )

            # 1. Extract
            raw_data = self.extract()
            if not raw_data:
                logger.info(f"[{self.job_name}] No data found. Exiting.")
                return 0

            # 2. Transform
            transformed_data = self.transform(raw_data)

            # 3. Truncate Staging
            self._truncate_staging()

            # 4. Load to Staging
            self._load_to_staging(transformed_data)

            # 5. Execute Merge
            self._execute_merge()

            # 6. Cleanup - Re-validate for type safety (cheap vs BQ/Network ops)
            # Use transformed_data to ensure all fields required by schema are present
            cleanup_models = [
                self.schema_model.model_validate(d) for d in transformed_data
            ]
            self.cleanup(cleanup_models)

            logger.info(f"[{self.job_name}] Pipeline finished successfully.")
            return len(transformed_data)

        except Exception as e:
            logger.error(f"[{self.job_name}] Pipeline FAILED: {str(e)}", exc_info=True)
            # CRITICAL: Re-raise to ensure job failure is reported to Cloud Run
            raise
