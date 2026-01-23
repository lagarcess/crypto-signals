"""
Price Patch Pipeline (Issue #141).

This pipeline repairs historical BigQuery records with $0.00 exit prices.
Runs once for historical repair, then daily for new records.

Pattern: "Query-Fetch-Update" (same as FeePatchPipeline from Issue #140)
1. Query: Get BigQuery rows where exit_fill_price = 0.0 and exit_order_id IS NOT NULL
2. Fetch: Call Alpaca Orders API for filled_avg_price
3. Update: Patch BigQuery with actual exit price and set exit_price_finalized = TRUE
"""

from typing import List

from google.cloud import bigquery
from loguru import logger

from crypto_signals.config import get_settings, get_trading_client
from crypto_signals.engine.execution import ExecutionEngine


class PricePatchPipeline:
    """
    Pipeline to repair historical exit prices in BigQuery.

    Runs daily before signal generation to finalize exit prices for closed trades.
    """

    # Configuration Constants
    MAX_TRADES_PER_RUN = 100  # Batch size for performance and rate limiting

    def __init__(self):
        """Initialize the pipeline."""
        settings = get_settings()
        self.bq_client = bigquery.Client(project=settings.GOOGLE_CLOUD_PROJECT)

        # Environment-aware table routing
        env_suffix = "" if settings.ENVIRONMENT == "PROD" else "_test"
        self.fact_table_id = (
            f"{settings.GOOGLE_CLOUD_PROJECT}.crypto_analytics.fact_trades{env_suffix}"
        )

        self.execution_engine = ExecutionEngine(trading_client=get_trading_client())

    def run(self) -> int:
        """
        Run the price patch pipeline.

        Returns:
            Number of trades patched
        """
        logger.info("[price_patch] Starting exit price repair...")

        # Step 1: Query unfinalized trades with exit_order_id
        unfinalized_trades = self._query_unfinalized_trades()

        if not unfinalized_trades:
            logger.info("[price_patch] No trades to repair")
            return 0

        logger.info(f"[price_patch] Found {len(unfinalized_trades)} trades to repair")

        # Step 2: Fetch exit prices and update BigQuery
        patched_count = 0
        for trade in unfinalized_trades:
            if self._patch_trade_price(trade):
                patched_count += 1

        logger.info(
            f"[price_patch] Repaired {patched_count}/{len(unfinalized_trades)} trades"
        )
        return patched_count

    def _query_unfinalized_trades(self) -> List[dict]:
        """
        Query BigQuery for trades with $0.00 exit prices but valid exit_order_id.

        Returns:
            List of trade dictionaries
        """
        query = f"""
        SELECT
            trade_id,
            symbol,
            asset_class,
            entry_time,
            exit_time,
            exit_order_id,
            entry_price as entry_fill_price,
            exit_price as current_exit_price,
            qty,
            ds
        FROM `{self.fact_table_id}`
        WHERE (exit_price_finalized = FALSE OR exit_price_finalized IS NULL)
          AND exit_order_id IS NOT NULL
          AND exit_price = 0.0
          AND status = 'CLOSED'
        ORDER BY exit_time DESC
        LIMIT {self.MAX_TRADES_PER_RUN}
        """

        query_job = self.bq_client.query(query)
        results = query_job.result()

        return [dict(row) for row in results]

    def _patch_trade_price(self, trade: dict) -> bool:
        """
        Fetch actual exit price from Alpaca and update BigQuery.

        Args:
            trade: Trade dictionary from BigQuery

        Returns:
            True if patched successfully
        """
        try:
            exit_order_id = trade.get("exit_order_id")
            if not exit_order_id:
                logger.warning(
                    f"[price_patch] No exit_order_id for trade {trade['trade_id']}, skipping"
                )
                return False

            # Fetch order details from Alpaca
            exit_order = self.execution_engine.get_order_details(exit_order_id)

            if not exit_order:
                logger.warning(f"[price_patch] Order {exit_order_id} not found in Alpaca")
                return False

            # Extract exit fill price
            actual_exit_price = None
            if exit_order.filled_avg_price:
                actual_exit_price = float(exit_order.filled_avg_price)

            if not actual_exit_price or actual_exit_price == 0.0:
                logger.warning(
                    f"[price_patch] Order {exit_order_id} has no fill price "
                    f"(status: {exit_order.status})"
                )
                return False

            # Recalculate PnL with actual exit price
            entry_price = trade.get("entry_fill_price", 0.0)
            qty = trade.get("qty", 0.0)

            if entry_price > 0 and qty > 0:
                # Simplified PnL (actual calculation in trade_archival.py is more complex)
                pnl_usd = (actual_exit_price - entry_price) * qty
            else:
                pnl_usd = 0.0

            # Update BigQuery
            update_query = f"""
            UPDATE `{self.fact_table_id}`
            SET
                exit_price_finalized = TRUE,
                exit_price = @actual_exit_price,
                exit_price_reconciled_at = CURRENT_TIMESTAMP(),
                pnl_usd = @pnl_usd
            WHERE trade_id = @trade_id
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(
                        "actual_exit_price", "FLOAT64", actual_exit_price
                    ),
                    bigquery.ScalarQueryParameter("pnl_usd", "FLOAT64", pnl_usd),
                    bigquery.ScalarQueryParameter(
                        "trade_id", "STRING", trade["trade_id"]
                    ),
                ]
            )

            update_job = self.bq_client.query(update_query, job_config=job_config)
            update_job.result()

            logger.info(
                f"[price_patch] Patched {trade['trade_id']}: "
                f"${trade['current_exit_price']:.2f} → ${actual_exit_price:.2f} "
                f"(PnL: ${pnl_usd:.2f})"
            )

            return True

        except Exception as e:
            logger.error(f"[price_patch] Failed to patch {trade['trade_id']}: {e}")
            return False
