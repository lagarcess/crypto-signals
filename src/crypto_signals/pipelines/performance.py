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
            for row in results:
                return row.cnt > 0
            return False
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

        # 2. Advanced Metrics Implementation
        # We use window functions to calculate cumulative metrics up to T-1.
        # Sharpe and Sortino are annualized assuming 365 trading days (Crypto).
        # Max Drawdown is calculated using the configured baseline capital.
        baseline_capital = self.settings.PERFORMANCE_BASELINE_CAPITAL

        query = f"""
            WITH daily_strategy_metrics AS (
                SELECT
                    ds,
                    strategy_id,
                    SUM(total_pnl) as daily_pnl,
                    SUM(trade_count) as daily_trades,
                    SAFE_DIVIDE(SUM(win_rate * trade_count), SUM(trade_count)) as daily_win_rate
                FROM `{self.source_table_id}`
                GROUP BY ds, strategy_id
            ),
            historical_metrics AS (
                SELECT
                    ds,
                    strategy_id,
                    daily_pnl,
                    daily_trades,
                    daily_win_rate,
                    SUM(daily_trades) OVER (PARTITION BY strategy_id ORDER BY ds) as total_trades,
                    SAFE_DIVIDE(
                        SUM(daily_win_rate * daily_trades) OVER (PARTITION BY strategy_id ORDER BY ds),
                        SUM(daily_trades) OVER (PARTITION BY strategy_id ORDER BY ds)
                    ) as win_rate,
                    -- Profit Factor: SUM(Gain) / ABS(SUM(Loss))
                    SAFE_DIVIDE(
                        SUM(IF(daily_pnl > 0, daily_pnl, 0)) OVER (PARTITION BY strategy_id ORDER BY ds),
                        ABS(SUM(IF(daily_pnl < 0, daily_pnl, 0)) OVER (PARTITION BY strategy_id ORDER BY ds))
                    ) as profit_factor,
                    -- Annualized Sharpe (assuming 365 days for Crypto)
                    SAFE_DIVIDE(
                        AVG(daily_pnl) OVER (PARTITION BY strategy_id ORDER BY ds),
                        STDDEV(daily_pnl) OVER (PARTITION BY strategy_id ORDER BY ds)
                    ) * SQRT(365) as sharpe_ratio,
                    -- Annualized Sortino
                    SAFE_DIVIDE(
                        AVG(daily_pnl) OVER (PARTITION BY strategy_id ORDER BY ds),
                        STDDEV(IF(daily_pnl < 0, daily_pnl, NULL)) OVER (PARTITION BY strategy_id ORDER BY ds)
                    ) * SQRT(365) as sortino_ratio,
                    -- Max Drawdown calculation using configured baseline capital
                    {baseline_capital} + SUM(daily_pnl) OVER (PARTITION BY strategy_id ORDER BY ds) as equity
                FROM daily_strategy_metrics
            ),
            drawdown_calc AS (
                SELECT
                    *,
                    MAX(equity) OVER (PARTITION BY strategy_id ORDER BY ds) as peak_equity
                FROM historical_metrics
            ),
            max_drawdown_calc AS (
                SELECT
                    *,
                    SAFE_DIVIDE(peak_equity - equity, peak_equity) as current_drawdown
                FROM drawdown_calc
            ),
            final_metrics AS (
                SELECT
                    ds,
                    strategy_id,
                    CAST(total_trades AS INT64) as total_trades,
                    win_rate,
                    IFNULL(profit_factor, 1.0) as profit_factor,
                    IFNULL(sharpe_ratio, 0.0) as sharpe_ratio,
                    IFNULL(sortino_ratio, 0.0) as sortino_ratio,
                    MAX(current_drawdown) OVER (PARTITION BY strategy_id ORDER BY ds) * 100.0 as max_drawdown_pct,
                    0.0 as alpha,
                    0.0 as beta
                FROM max_drawdown_calc
            )
            SELECT * FROM final_metrics
            WHERE ds = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
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
