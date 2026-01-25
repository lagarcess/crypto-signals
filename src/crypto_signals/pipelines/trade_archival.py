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

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, List

import pandas as pd
from alpaca.common.exceptions import APIError
from google.cloud import firestore
from loguru import logger

from crypto_signals.config import (
    get_crypto_data_client,
    get_settings,
    get_stock_data_client,
    get_trading_client,
)
from crypto_signals.domain.schemas import ExitReason, OrderSide, TradeExecution
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.pipelines.base import BigQueryPipelineBase


class TradeArchivalPipeline(BigQueryPipelineBase):
    """
    Pipeline to archive closed trades from Firestore to BigQuery.

    Enriches Firestore data with precise execution details from Alpaca.
    """

    def __init__(self):
        """Initialize the pipeline with specific configuration."""
        # Configure BigQuery settings
        # Environment-aware table routing
        settings = get_settings()
        env_suffix = "" if settings.ENVIRONMENT == "PROD" else "_test"

        super().__init__(
            job_name="trade_archival",
            staging_table_id=(
                f"{settings.GOOGLE_CLOUD_PROJECT}.crypto_analytics.stg_trades_import{env_suffix}"
            ),
            fact_table_id=(
                f"{settings.GOOGLE_CLOUD_PROJECT}.crypto_analytics.fact_trades{env_suffix}"
            ),
            id_column="trade_id",
            partition_column="ds",
            schema_model=TradeExecution,
        )

        # Initialize Source Clients
        # Note: We use the project from settings, same as BQ
        self.firestore_client = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)

        # Environment-aware collection routing
        self.source_collection = (
            "live_positions" if settings.ENVIRONMENT == "PROD" else "test_positions"
        )

        self.alpaca = get_trading_client()

        # Initialize MarketDataProvider with required clients
        stock_client = get_stock_data_client()
        crypto_client = get_crypto_data_client()
        self.market_provider = MarketDataProvider(stock_client, crypto_client)

        # Initialize ExecutionEngine for fee tier queries (Issue #140)
        # Reused across all trades to avoid repeated instantiation
        from crypto_signals.engine.execution import ExecutionEngine

        self.execution_engine = ExecutionEngine()

    def extract(self) -> List[Any]:
        """
        Extract CLOSED positions from Firestore.

        Returns:
            List[dict]: List of raw position dictionaries.
        """
        logger.info(f"[{self.job_name}] extracting CLOSED positions from Firestore...")

        # Query CLOSED positions (deleted after successful merge via cleanup)
        docs = (
            self.firestore_client.collection(self.source_collection)
            .where(field_path="status", op_string="==", value="CLOSED")
            .stream()
        )

        raw_data = []
        for doc in docs:
            data = doc.to_dict()
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

        # Symbol-based cache to prevent redundant API calls
        # Key: f"{symbol}_{asset_class}", Value: DataFrame of daily bars
        symbol_bars_cache: dict = {}

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
                            f"[{self.job_name}] Order {client_order_id} not found in Alpaca. "
                            "Assuming Theoretical/Paper trade. Falling back to Firestore data."
                        )
                        # Create synthetic order from Firestore data
                        # Robustness: Ensure qty is handled if missing
                        qty_fallback = pos.get("qty", 0.0) or 0.0
                        order = SimpleNamespace(
                            id=None,
                            filled_avg_price=pos.get("entry_fill_price", 0.0),
                            filled_qty=qty_fallback,
                            side=pos.get("side", "buy").lower(),
                        )
                    else:
                        raise e

                # 2. Calculate Derived Metrics
                # Note: Alpaca 'filled_avg_price' is the source of truth
                # for execution price
                entry_price_val = (
                    float(order.filled_avg_price) if order.filled_avg_price else 0.0
                )
                qty = float(order.filled_qty) if order.filled_qty else 0.0

                # Target price from original Signal (stored in Firestore position)
                # This is the price we *intended* to enter at
                # Use target_entry_price if available, fallback to entry_fill_price for legacy
                target_price = float(
                    pos.get("target_entry_price")
                    if pos.get("target_entry_price") is not None
                    else pos.get("entry_fill_price", 0.0)
                )

                # Broker's order ID for auditability (links to Alpaca dashboard)
                alpaca_order_id = str(order.id) if order.id else None

                # Get exit price from Firestore document, default to 0.0 if missing
                exit_price_val = float(pos.get("exit_fill_price", 0.0))

                # Weighted Average Exit Price for Partial Fills
                scaled_out_prices = pos.get("scaled_out_prices", [])
                if scaled_out_prices:
                    total_exit_val = 0.0
                    total_exit_qty = 0.0

                    for scale in scaled_out_prices:
                        s_qty = float(scale.get("qty", 0.0))
                        s_price = float(scale.get("price", 0.0))
                        total_exit_val += s_qty * s_price
                        total_exit_qty += s_qty

                    # Remaining quantity closed at exit_fill_price
                    # Use original_qty if available to determine total, else use current qty (which represents total traded)
                    original_qty = pos.get("original_qty")
                    total_qty_calc = (
                        float(original_qty) if original_qty else qty
                    )  # Fallback to order qty

                    remaining_qty = total_qty_calc - total_exit_qty
                    if remaining_qty > 0:
                        total_exit_val += remaining_qty * exit_price_val

                    if total_qty_calc > 0:
                        exit_price_val = total_exit_val / total_qty_calc

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
                # Fees: Use dynamic tier rate for initial estimate (T+0)
                # Actual fees will be reconciled via FeePatchPipeline (T+1+)
                fees_usd = 0.0
                fee_calculation_type = "ESTIMATED"
                fee_tier = None

                is_crypto = pos.get("asset_class") == "CRYPTO"

                if is_crypto:
                    # Get current fee tier for accurate estimate
                    tier_info = self.execution_engine.get_current_fee_tier()

                    # Use taker fee (conservative, most trades are takers)
                    taker_fee_pct = tier_info["taker_fee_pct"]
                    fee_tier = tier_info["tier_name"]

                    # Fee = (Entry Value + Exit Value) * taker_fee_pct / 100
                    entry_val = entry_price_val * qty
                    exit_val = exit_price_val * qty
                    fees_usd = (entry_val + exit_val) * (taker_fee_pct / 100.0)

                    logger.debug(
                        f"Using estimated fees for {pos.get('symbol')}: ${fees_usd:.2f} ({fee_tier})"
                    )

                # PnL Calculation using ALPACA entry price (Truth) vs
                # Firestore Exit Price
                pnl_gross = (exit_price_val - entry_price_val) * qty

                # Source of Truth: Alpaca Order Side (Entry Order)
                # Validates if we opened Long (Buy) or Short (Sell)
                # Cast to string to handle Enum or str types robustly
                order_side_str = str(order.side).lower()

                if order_side_str == OrderSide.SELL.value:  # Short
                    pnl_gross = (entry_price_val - exit_price_val) * qty

                # --- MFE Calculation ---
                max_favorable_excursion = None
                try:
                    # Build cache key from symbol and asset class
                    symbol = pos.get("symbol")
                    asset_class = pos.get("asset_class", "CRYPTO")
                    cache_key = f"{symbol}_{asset_class}"

                    # Check cache before fetching
                    if cache_key in symbol_bars_cache:
                        bars_df = symbol_bars_cache[cache_key]
                    else:
                        # Fetch bars and store in cache
                        bars_df = self.market_provider.get_daily_bars(
                            symbol=symbol,
                            asset_class=asset_class,
                            lookback_days=None,
                        )
                        symbol_bars_cache[cache_key] = bars_df

                    if not bars_df.empty:
                        # Filter for trade window
                        trade_window = bars_df[
                            (bars_df.index >= pd.Timestamp(entry_time).floor("D"))
                            & (bars_df.index <= pd.Timestamp(exit_time).ceil("D"))
                        ]

                        if not trade_window.empty:
                            if order_side_str == OrderSide.BUY.value:
                                highest_price = trade_window["high"].max()
                                max_favorable_excursion = highest_price - entry_price_val
                            else:  # Short
                                lowest_price = trade_window["low"].min()
                                mfe = entry_price_val - lowest_price
                                max_favorable_excursion = mfe

                except Exception as e:
                    logger.warning(
                        f"Failed to calculate MFE for {pos.get('position_id')}: {e}"
                    )

                pnl_usd = pnl_gross - fees_usd

                # PnL % should be a percentage value (e.g. 5.0 for 5%), not a ratio
                cost_basis = entry_price_val * qty
                pnl_pct = (pnl_usd / cost_basis * 100.0) if cost_basis else 0.0

                # Slippage Calculation (Direction-Aware)
                # For LONG: positive slippage = filled higher (unfavorable)
                # For SHORT: positive slippage = filled lower (unfavorable)
                if target_price:
                    if order_side_str == OrderSide.BUY.value:  # Long
                        # Long: filled higher than target = positive slippage (bad)
                        slippage_pct = round(
                            ((entry_price_val - target_price) / target_price * 100.0), 4
                        )
                    else:  # Short
                        # Short: filled lower than target = positive slippage (bad)
                        # Inverted formula: (target - actual) / target
                        slippage_pct = round(
                            ((target_price - entry_price_val) / target_price * 100.0), 4
                        )
                else:
                    slippage_pct = 0.0

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
                    slippage_pct=slippage_pct,
                    trade_duration=duration,
                    exit_reason=ExitReason(pos.get("exit_reason", ExitReason.TP1.value)),
                    max_favorable_excursion=max_favorable_excursion,
                    # Propagate Discord thread_id for social context analytics
                    discord_thread_id=pos.get("discord_thread_id"),
                    # Propagate final trailing stop for Runner (TP3) exit analysis
                    trailing_stop_final=pos.get("trailing_stop_final"),
                    # New fields for slippage analysis and broker auditability
                    target_entry_price=target_price,
                    alpaca_order_id=alpaca_order_id,
                    # Exit order ID for reconciliation and fill tracking
                    exit_order_id=pos.get("exit_order_id"),
                    # CFEE Reconciliation Fields (Issue #140)
                    fee_finalized=False,  # Will be reconciled T+1 via FeePatchPipeline
                    actual_fee_usd=None,  # Populated after CFEE reconciliation
                    fee_calculation_type=fee_calculation_type,  # "ESTIMATED" initially
                    fee_tier=fee_tier,  # e.g., "Tier 0"
                    entry_order_id=pos.get("entry_order_id"),  # For CFEE attribution
                    fee_reconciled_at=None,  # Populated after reconciliation
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

    def cleanup(self, data: List[TradeExecution]) -> None:
        """
        Delete processed positions from Firestore.

        Args:
            data: List of successfully loaded TradeExecution models.
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
            # item is now a TradeExecution Pydantic model
            # We need the Original ID used in Firestore.
            # In transform, we mapped trade_id -> position_id.
            doc_id = item.trade_id

            # Assumption: Firestore Doc ID == position_id
            # (which is usually true in this design)
            # If Doc ID was random, we'd need to have passed it through.
            # Let's assume Doc ID KEY strategy is used or we query ID.
            # Usually: collection('live_positions').document(position_id)
            ref = self.firestore_client.collection(self.source_collection).document(
                doc_id
            )
            batch.delete(ref)
            count += 1

            if count >= 400:  # Firestore batch limit is 500
                batch.commit()
                batch = self.firestore_client.batch()
                count = 0

        if count > 0:
            batch.commit()

        logger.info(f"[{self.job_name}] Cleanup complete.")
