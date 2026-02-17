"""
Strategy Performance Pipeline.

This pipeline reads from the Aggregation Table (agg_strategy_daily),
calculates summary performance metrics per strategy, and writes to
the Performance Table (summary_strategy_performance).

It implements the "Aggregation Layer" pattern to support fast dashboards.
"""

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

    def extract(self) -> List[Any]:
        """
        Execute BigQuery aggregation query on agg_strategy_daily.

        Returns:
            List[dict]: Performance data rows.
        """
        logger.info(
            f"[{self.job_name}] Calculating performance from {self.source_table_id}..."
        )

        # Basic aggregation query.
        # Complex metrics (Sharpe, Sortino, Alpha, Beta) are set to 0.0/1.0
        # as they require complex time-series analysis not yet implemented in SQL.
        query = f"""
            SELECT
                ds,
                strategy_id,
                CAST(SUM(trade_count) AS INT64) as total_trades,
                SAFE_DIVIDE(SUM(win_rate * trade_count), SUM(trade_count)) as win_rate,
                1.0 as profit_factor,
                0.0 as sharpe_ratio,
                0.0 as sortino_ratio,
                0.0 as max_drawdown_pct,
                0.0 as alpha,
                0.0 as beta
            FROM `{self.source_table_id}`
            GROUP BY ds, strategy_id
        """

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
