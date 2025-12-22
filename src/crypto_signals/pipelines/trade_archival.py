"""
Trade Archival Pipeline.

This pipeline moves CLOSED positions from Firestore (Operational)
to BigQuery (Analytical). It enriches the data by fetching exact execution
details (fees, fill times) from the Alpaca API.

Pattern: "Enrich-Extract-Load"
1. Extract: Get CLOSED positions from Firestore.
2. Transform: Call Alpaca API for each position to get truth data (fees, times).
3. Load: Push to BigQuery via BasePipeline (Truncate->Staging->Merge).
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, List

import pandas as pd
from alpaca.common.exceptions import APIError
from google.cloud import firestore

from crypto_signals.config import get_trading_client, settings
from crypto_signals.domain.schemas import OrderSide, TradeExecution
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.pipelines.base import BigQueryPipelineBase

logger = logging.getLogger(__name__)


class TradeArchivalPipeline(BigQueryPipelineBase):
    """
    Pipeline to archive closed trades from Firestore to BigQuery.

    Enriches Firestore data with precise execution details from Alpaca.
    """

    def __init__(self):
        """Initialize the pipeline with specific configuration."""
        # Configure BigQuery settings
        super().__init__(
            job_name="trade_archival",
            staging_table_id=(
                f"{settings().GOOGLE_CLOUD_PROJECT}.crypto_sentinel.stg_trades_import"
            ),
            fact_table_id=(
                f"{settings().GOOGLE_CLOUD_PROJECT}.crypto_sentinel.fact_trades"
            ),
            id_column="trade_id",
            partition_column="ds",
            schema_model=TradeExecution,
        )

        # Initialize Source Clients
        # Note: We use the project from settings, same as BQ
        self.firestore_client = firestore.Client(
            project=settings().GOOGLE_CLOUD_PROJECT
        )
        self.alpaca = get_trading_client()
        self.market_provider = MarketDataProvider()

    def extract(self) -> List[Any]:
        """
        Extract CLOSED positions from Firestore.

        Returns:
            List[dict]: List of raw position dictionaries.
        """
        logger.info(f"[{self.job_name}] extracting CLOSED positions from Firestore...")

        # Query: status == 'CLOSED'
        # We scan live_positions for any trade that is marked closed
        # The Cleanup step will delete them after successful load,
        # ensuring we don't re-process forever.
        docs = (
            self.firestore_client.collection("live_positions")
            .where(field_path="status", op_string="==", value="CLOSED")
            .stream()
        )

        # Convert to list of dicts, keeping the ID if needed
        # (though position_id is in body)
        raw_data = []
        for doc in docs:
            data = doc.to_dict()
            # Ensure we strictly follow what's in the DB,
            # but Firestore might return None for missing fields if not careful.
            if data:
                raw_data.append(data)

        logger.info(f"[{self.job_name}] extracted {len(raw_data)} closed positions.")
        return raw_data

    def transform(self, raw_data: List[Any]) -> List[dict]:
        """
        Enrich raw Firestore positions with Alpaca execution details.

        Args:
            raw_data: List of position dictionaries from Firestore.

        Returns:
            List[dict]: Enriched data matching TradeExecution schema (as dicts).
        """
        logger.info(
            f"[{self.job_name}] Enriching {len(raw_data)} trades with Alpaca data..."
        )

        transformed = []

        for idx, pos in enumerate(raw_data):
            # Rate Limit Safety: Sleep 100ms between requests
            # (skip before first request)
            if idx > 0:
                time.sleep(0.1)

            try:
                # 1. Fetch Order Details from Alpaca to get Fees and Exact Times
                # The position_id in Firestore IS the Client Order ID from Alpaca
                # (idempotency key)
                client_order_id = pos.get("position_id")

                try:
                    # Fetch order by client_order_id to ensure we get the specific trade
                    order = self.alpaca.get_order_by_client_order_id(client_order_id)
                except APIError as e:
                    # Specific handling for 404/Not Found
                    # In Alpaca, the HTTP status code may live on the nested
                    # http_error object.
                    status_code = getattr(
                        getattr(e, "http_error", None), "status_code", None
                    )
                    if status_code == 404 or "not found" in str(e).lower():
                        logger.warning(
                            f"[{self.job_name}] Order {client_order_id} "
                            "not found: Skipping."
                        )
                        continue
                    raise e

                # 2. Calculate Derived Metrics
                # Note: Alpaca 'filled_avg_price' is the source of truth
                # for execution price
                entry_price_val = (
                    float(order.filled_avg_price) if order.filled_avg_price else 0.0
                )
                qty = float(order.filled_qty) if order.filled_qty else 0.0

                # Get exit price from Firestore document, default to 0.0 if missing
                exit_price_val = float(pos.get("exit_fill_price", 0.0))

                # Timestamps
                entry_time_str = pos.get("entry_time")  # Should be in doc
                exit_time_str = pos.get("exit_time")  # Should be in doc

                # Parse or default
                def parse_dt(val):
                    if isinstance(val, datetime):
                        return val
                    try:
                        return datetime.fromisoformat(str(val))
                    except (ValueError, TypeError) as exc:
                        logger.warning(
                            f"Failed to parse datetime value '{val}'; defaulting to now. Error: {exc}"
                        )
                        return datetime.now(timezone.utc)

                entry_time = parse_dt(entry_time_str)
                exit_time = parse_dt(exit_time_str)

                # CALCULATIONS
                # Fees: Hard to get exact without activity ID.
                # TODO: Implement exact fee fetching via TradeActivity endpoint
                # in Phase 4
                fees_usd = 0.0

                # PnL Calculation using ALPACA entry price (Truth) vs
                # Firestore Exit Price
                pnl_gross = (exit_price_val - entry_price_val) * qty

                # Source of Truth: Alpaca Order Side (Entry Order)
                # Validates if we opened Long (Buy) or Short (Sell)
                # Cast to string to handle Enum or str types robustly
                order_side_str = str(order.side).lower()

                if order_side_str == OrderSide.SELL.value:  # Short
                    pnl_gross = (entry_price_val - exit_price_val) * qty

                pnl_usd = pnl_gross - fees_usd

                # --- MFE Calculation ---
                max_favorable_excursion = None
                try:
                    # Fetch bars for MFE calculation
                    bars_df = self.market_provider.get_daily_bars(
                        symbol=pos.get("symbol"),
                        asset_class=pos.get("asset_class", "CRYPTO"),
                        lookback_days=None,
                    )

                    if not bars_df.empty:
                        # Filter for trade window
                        trade_window = bars_df[
                            (bars_df.index >= pd.Timestamp(entry_time).floor("D"))
                            & (bars_df.index <= pd.Timestamp(exit_time).ceil("D"))
                        ]

                        if not trade_window.empty:
                            if order_side_str == OrderSide.BUY.value:
                                highest_price = trade_window["high"].max()
                                max_favorable_excursion = (
                                    highest_price - entry_price_val
                                )
                            else:  # Short
                                lowest_price = trade_window["low"].min()
                                max_favorable_excursion = entry_price_val - lowest_price

                except Exception as e:
                    logger.warning(
                        f"Failed to calculate MFE for {pos.get('position_id')}: {e}"
                    )

                pnl_usd = pnl_gross - fees_usd

                # PnL % should be a percentage value (e.g. 5.0 for 5%), not a ratio
                cost_basis = entry_price_val * qty
                pnl_pct = (pnl_usd / cost_basis * 100.0) if cost_basis else 0.0

                duration = int((exit_time - entry_time).total_seconds())

                # Construct Model
                trade = TradeExecution(
                    ds=entry_time.date(),
                    trade_id=pos.get("position_id"),
                    account_id=pos.get("account_id"),
                    strategy_id=pos.get("strategy_id"),
                    asset_class=pos.get("asset_class", "CRYPTO"),
                    symbol=pos.get("symbol"),
                    side=pos.get("side"),
                    qty=qty,  # Authenticated from Alpaca
                    entry_price=entry_price_val,  # Authenticated from Alpaca
                    exit_price=exit_price_val,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    pnl_usd=round(pnl_usd, 2),
                    pnl_pct=round(pnl_pct, 4),
                    fees_usd=round(fees_usd, 2),
                    slippage_pct=0.0,
                    trade_duration=duration,
                    exit_reason=pos.get("exit_reason", "TP1"),  # Default or map
                    max_favorable_excursion=max_favorable_excursion,
                )

                # Validate and Dump to JSON (BasePipeline expects dicts)
                transformed.append(trade.model_dump(mode="json"))

            except Exception as e:
                # Log error but don't stop the whole batch?
                # For now, log and skip specific bad records to avoid blocking
                # the pipeline.
                logger.error(
                    f"[{self.job_name}] Failed to transform position "
                    f"{pos.get('position_id')}: {e}"
                )
                continue

        return transformed

    def cleanup(self, data: List[dict]) -> None:
        """
        Delete processed positions from Firestore.

        Args:
            data: List of successfully loaded data dicts (or models).
        """
        if not data:
            return

        logger.info(
            f"[{self.job_name}] Cleaning up {len(data)} records from Firestore..."
        )

        # Batch delete
        batch = self.firestore_client.batch()
        count = 0

        for item in data:
            # item is a dict from BIGQUERY format or Pydantic dump.
            # We need the Original ID used in Firestore.
            # In transform, we mapped trade_id -> position_id.
            doc_id = item.get("trade_id")

            # Assumption: Firestore Doc ID == position_id
            # (which is usually true in this design)
            # If Doc ID was random, we'd need to have passed it through.
            # Let's assume Doc ID KEY strategy is used or we query ID.
            # Usually: collection('live_positions').document(position_id)
            ref = self.firestore_client.collection("live_positions").document(doc_id)
            batch.delete(ref)
            count += 1

            if count >= 400:  # Firestore batch limit is 500
                batch.commit()
                batch = self.firestore_client.batch()
                count = 0

        if count > 0:
            batch.commit()

        logger.info(f"[{self.job_name}] Cleanup complete.")
