"""
Daily Strategy Aggregation Pipeline.

This pipeline reads from the BigQuery Fact Table (fact_trades),
aggregates data by strategy, symbol, and date, and writes to
the Aggregation Table (agg_strategy_daily).

It implements the "Aggregation Layer" pattern to support fast dashboards.
"""

import datetime
from typing import Any, List, Type

from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError
from loguru import logger
from pydantic import BaseModel

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import AggStrategyDaily
from crypto_signals.pipelines.base import BigQueryPipelineBase


class DailyStrategyAggregation(BigQueryPipelineBase):
    """
    Pipeline to aggregate daily strategy performance.

    Reads from: fact_trades
    Writes to: agg_strategy_daily
    """

    def __init__(self):
        """Initialize the pipeline."""
        settings = get_settings()
        project_id = settings.GOOGLE_CLOUD_PROJECT
        env_suffix = "" if settings.ENVIRONMENT == "PROD" else "_test"

        # Define table IDs
        self.source_table_id = f"{project_id}.crypto_analytics.fact_trades{env_suffix}"
        staging_table_id = f"{project_id}.crypto_analytics.stg_agg_strategy_daily{env_suffix}"
        fact_table_id = f"{project_id}.crypto_analytics.agg_strategy_daily{env_suffix}"

        super().__init__(
            job_name="agg_strategy_daily",
            staging_table_id=staging_table_id,
            fact_table_id=fact_table_id,
            id_column="agg_id",
            partition_column="ds",
            schema_model=AggStrategyDaily,
        )

    def _generate_bq_schema(self, model: Type[BaseModel]) -> List[bigquery.SchemaField]:
        """
        Dynamically generate BigQuery schema from Pydantic model.
        """
        schema = []

        # Simple mapping for this specific use case
        # For a more robust solution, we would iterate over fields and handle nested models
        # But AggStrategyDaily is flat.

        type_mapping = {
            str: "STRING",
            int: "INTEGER",
            float: "FLOAT",
            bool: "BOOLEAN",
            datetime.datetime: "TIMESTAMP",
            datetime.date: "DATE",
        }

        for name, field_info in model.model_fields.items():
            # Handle Optional types if needed, but for AggStrategyDaily all are required
            # Unwrapping logic could be added here similar to SchemaGuardian if models get complex

            python_type = field_info.annotation

            # Basic unwrapping for simple Optional (if any future changes add them)
            # (Simplified version of SchemaGuardian._unwrap_type)
            import typing
            origin = typing.get_origin(python_type)
            if origin is typing.Union:
                args = typing.get_args(python_type)
                for arg in args:
                    if arg is not type(None):
                        python_type = arg
                        break

            # Ensure python_type is a type and not None for mypy
            if python_type is None:
                 bq_type = "STRING"
            else:
                 bq_type = type_mapping.get(python_type, "STRING") # type: ignore

            mode = "REQUIRED"  # Default to required as per original implementation

            # If field allows None, mode should be NULLABLE.
            # In current AggStrategyDaily, all are "..." (Required) except maybe implicitly?
            # Let's check the schema. All are "..."

            schema.append(bigquery.SchemaField(name, bq_type, mode=mode))

        return schema

    def _create_table_if_not_exists(self, table_id: str) -> None:
        """
        Create the BigQuery table if it does not exist.

        Uses the schema defined in AggStrategyDaily.
        """
        try:
            self.bq_client.get_table(table_id)
            logger.debug(f"[{self.job_name}] Table {table_id} already exists.")
            return
        except NotFound:
            logger.info(f"[{self.job_name}] Table {table_id} not found. Creating...")

        # Construct Schema dynamically from Pydantic model
        schema = self._generate_bq_schema(self.schema_model)

        table = bigquery.Table(table_id, schema=schema)

        # Configure Partitioning
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="ds",  # Partition by 'ds' column
        )

        try:
            self.bq_client.create_table(table)
            logger.info(f"[{self.job_name}] Created table {table_id}.")
        except Exception as e:
            logger.error(f"[{self.job_name}] Failed to create table {table_id}: {e}")
            raise

    def run(self) -> int:
        """
        Override run to ensure tables exist before execution.
        """
        # Ensure Fact and Staging tables exist
        self._create_table_if_not_exists(self.fact_table_id)
        self._create_table_if_not_exists(self.staging_table_id)

        return super().run()

    def extract(self) -> List[Any]:
        """
        Execute BigQuery aggregation query on fact_trades.

        Returns:
            List[dict]: Aggregated data rows.
        """
        logger.info(f"[{self.job_name}] Aggregating data from {self.source_table_id}...")

        # Note: SAFE_DIVIDE handles division by zero.
        # win_rate is defined as COUNT(pnl > 0) / TOTAL.
        query = f"""
            SELECT
                ds,
                CONCAT(CAST(ds AS STRING), '|', strategy_id, '|', symbol) as agg_id,
                strategy_id,
                symbol,
                SUM(pnl_usd) as total_pnl,
                SAFE_DIVIDE(COUNTIF(pnl_usd > 0), COUNT(*)) as win_rate,
                COUNT(*) as trade_count
            FROM `{self.source_table_id}`
            GROUP BY ds, strategy_id, symbol
        """

        try:
            query_job = self.bq_client.query(query)
            results = query_job.result()  # Wait for completion

            rows = [dict(row) for row in results]
            logger.info(f"[{self.job_name}] Extracted {len(rows)} aggregated records.")
            return rows

        except (GoogleCloudError, GoogleAPICallError) as e:
            logger.error(f"[{self.job_name}] Failed to extract data: {e}")
            raise
        except Exception as e:
             # Catch-all for other unforeseen errors to ensure logging
            logger.error(f"[{self.job_name}] Unexpected error during extraction: {e}")
            raise

    def cleanup(self, data: List[BaseModel]) -> None:
        """
        No-op cleanup.

        Since we are reading from BigQuery (Analytical) and writing to BigQuery (Analytical),
        we do not delete the source data (fact_trades).
        """
        pass
