"""
Daily Strategy Aggregation Pipeline.

This pipeline reads from the BigQuery Fact Table (fact_trades),
aggregates data by strategy, symbol, and date, and writes to
the Aggregation Table (agg_strategy_daily).

It implements the "Aggregation Layer" pattern to support fast dashboards.
"""

from typing import Any, List

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
        staging_table_id = (
            f"{project_id}.crypto_analytics.stg_agg_strategy_daily{env_suffix}"
        )
        fact_table_id = f"{project_id}.crypto_analytics.agg_strategy_daily{env_suffix}"

        super().__init__(
            job_name="agg_strategy_daily",
            staging_table_id=staging_table_id,
            fact_table_id=fact_table_id,
            id_column="agg_id",
            partition_column="ds",
            schema_model=AggStrategyDaily,
        )

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

        # Construct Schema dynamically using SchemaGuardian
        from crypto_signals.engine.schema_guardian import SchemaGuardian

        guardian = SchemaGuardian(self.bq_client)
        schema = guardian.generate_schema(self.schema_model)

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
                SUM(pnl_usd) as total_pnl,
                SAFE_DIVIDE(COUNTIF(pnl_usd > 0), COUNT(*)) as win_rate,
                COUNT(*) as trade_count
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
