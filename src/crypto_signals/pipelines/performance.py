"""
Strategy Performance Pipeline.

This pipeline reads from the Aggregation Table (agg_strategy_daily),
calculates summary performance metrics per strategy, and writes to
the Performance Table (summary_strategy_performance).

It implements the "Aggregation Layer" pattern to support fast dashboards.
"""

from pathlib import Path
from typing import Any, List

from loguru import logger
from pydantic import BaseModel

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import StrategyPerformance
from crypto_signals.pipelines.base import BigQueryPipelineBase


class PerformancePipeline(BigQueryPipelineBase):
    """
    Pipeline to calculate summary strategy performance.

    Reads from: agg_strategy_daily
    Writes to: summary_strategy_performance
    """

    def __init__(self):
        """Initialize the pipeline."""
        settings = get_settings()
        project_id = settings.GOOGLE_CLOUD_PROJECT
        env_suffix = "" if settings.ENVIRONMENT == "PROD" else "_test"

        # Define table IDs
        self.source_table_id = (
            f"{project_id}.crypto_analytics.agg_strategy_daily{env_suffix}"
        )
        staging_table_id = (
            f"{project_id}.crypto_analytics.stg_performance_import{env_suffix}"
        )
        fact_table_id = (
            f"{project_id}.crypto_analytics.summary_strategy_performance{env_suffix}"
        )

        super().__init__(
            job_name="performance_pipeline",
            staging_table_id=staging_table_id,
            fact_table_id=fact_table_id,
            id_column="strategy_id",
            partition_column="ds",
            schema_model=StrategyPerformance,
        )

    def _check_t_minus_1_data(self) -> bool:
        """
        Check if data for T-1 is available in the source table.

        Returns:
            bool: True if data exists, False otherwise.
        """
        query = f"""
            SELECT COUNT(*) as cnt
            FROM `{self.source_table_id}`
            WHERE ds = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        """
        try:
            query_job = self.bq_client.query(query)
            results = query_job.result()
            result = next(iter(results), None)
            return result.cnt > 0 if result else False
        except Exception as e:
            logger.error(
                f"[{self.job_name}] Failed to check T-1 data availability.",
                extra={"error": str(e)},
            )
            return False

    def extract(self) -> List[Any]:
        """
        Execute BigQuery aggregation query on agg_strategy_daily.

        Returns:
            List[dict]: Performance data rows.
        """
        # 1. T-1 Architecture: Verify data availability
        if not self._check_t_minus_1_data():
            logger.warning(
                f"[{self.job_name}] No data found for T-1 in {self.source_table_id}. Skipping execution."
            )
            return []

        logger.info(
            f"[{self.job_name}] Calculating performance from {self.source_table_id}..."
        )

        # 2. Advanced Metrics Implementation: Load from SQL file
        query_path = Path(__file__).parent / "performance_query.sql"
        query_template = query_path.read_text()
        query = query_template.format(
            source_table_id=self.source_table_id,
            baseline_capital=self.settings.PERFORMANCE_BASELINE_CAPITAL,
        )

        try:
            query_job = self.bq_client.query(query)
            results = query_job.result()  # Wait for completion

            rows = [dict(row) for row in results]
            logger.info(f"[{self.job_name}] Extracted {len(rows)} performance records.")
            return rows

        except Exception as e:
            logger.error(
                f"[{self.job_name}] Failed to extract performance data.",
                extra={"error": str(e)},
            )
            raise

    def cleanup(self, data: List[BaseModel]) -> None:
        """
        No-op cleanup.
        """
        pass
