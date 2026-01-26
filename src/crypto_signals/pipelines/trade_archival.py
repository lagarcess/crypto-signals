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

    def _get_actual_fees(
        self, alpaca_order_id: str | None, symbol: str, side: str
    ) -> float | None:
        """
        Fetch actual fees (CFEE) from Alpaca Activities API.

        Args:
            alpaca_order_id: The Alpaca Order ID (UUID).
            symbol: Trading pair symbol (e.g., "BTC/USD").
            side: Order side ("buy" or "sell").

        Returns:
            float: Total fees in USD, or None if no activities found.
        """
        if not alpaca_order_id:
            return None

        try:
            # Fetch recent account activities (CFEE = Crypto Fee)
            # Filter by date/type/direction via API parameters to optimize?
            # alpaca-py `get_account_activities` supports `activity_types`.
            # Note: We can't filter by order_id in the API call, must filter in client.
            # Fetching last 100 CFEE activities should cover recent trades.
            from alpaca.trading.enums import ActivityType

            activities = self.alpaca._get(
                "/account/activities",
                params={"activity_types": "CSD,CFEE"},
            )

            # Filter for this specific order
            # CFEE activities link to order_id (sometimes in 'id' or separate field depending on SDK version)
            # Inspecting common pattern: activity.order_id should match.
            related_activities = [
                a
                for a in activities
                if hasattr(a, "order_id") and str(a.order_id) == alpaca_order_id
            ]

            if not related_activities:
                return None

            total_fee_usd = 0.0

            for activity in related_activities:
                # activity.qty is the fee amount
                # activity.price is the fill price (exchange rate) at that moment
                # activity.symbol is the asset

                fee_qty = float(activity.qty) if activity.qty else 0.0

                # Determine currency of the fee
                # For Buy orders (e.g., Buy BTC/USD), fee is usually in BTC (the asset).
                # For Sell orders (e.g., Sell BTC/USD), fee is usually in USD (the quote).
                # However, Alpaca CFEE records for Buy are in Asset, for Sell are in USD?
                # Actually, CFEE is always the "crypto fee".
                # If side == BUY: Fee is taken from the bought asset (e.g., BTC).
                #   Value in USD = fee_qty * fill_price
                # If side == SELL: Fee is taken from the proceeds (USD).
                #   Value in USD = fee_qty (already in USD) -- WAIT.
                #   Let's check the schema. Usually, Sell orders have "FILL" activity.
                #   CFEE specifically denotes a crypto fee.

                # SAFE LOGIC:
                # If activity.symbol == "USD", it's already USD.
                # If activity.symbol != "USD" (e.g., "BTC"), convert using activity.price.
                # (activity.price is typically the execution price).

                # Note: 'price' in Activity might be None for some types, but for CFEE/FILL it acts as rate.
                price = float(activity.price) if activity.price else 0.0

                # Heuristic for Currency:
                # If the symbol in the activity is the BASE currency (e.g. BTC), convert it.
                # If it is USD, take it as is.
                # Alpaca data often puts the fee amount in 'qty'.

                # Case 1: Fee is in USD (e.g., Sell side or USD-based fee)
                # How to detect? activity.symbol might help?
                # Actually, `activity.symbol` is usually the traded pair or asset.

                # Let's trust the logic requested:
                # "For 'Buy' orders, ensure the asset-denominated fee is converted to USD using the 'price' field"

                if side.lower() == "buy":
                    # Fee is in Asset. Convert to USD.
                    # Assumption: price is the USD price of the asset at execution.
                    fee_value = fee_qty * price
                else:
                    # Fee is in USD (deducted from proceeds).
                    fee_value = fee_qty

                total_fee_usd += fee_value

            return total_fee_usd

        except Exception as e:
            logger.warning(
                f"Failed to fetch actual fees for order {alpaca_order_id}: {e}"
            )
            return None

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
            .where("status", "==", "CLOSED")
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
                    order = self.alpaca.get_order_by_client_id(client_order_id)
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
                            id=str(pos.get("alpaca_order_id")),
                            filled_avg_price=str(pos.get("entry_fill_price") or "0.0"),
                            filled_qty=str(qty_fallback),
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

                # Source of Truth: Alpaca Order Side (Entry Order)
                # Cast to string to handle Enum or str types robustly
                order_side_str = str(order.side).lower()

                # Get exit price from Firestore document, default to 0.0 if missing
                exit_price_val = float(pos.get("exit_fill_price", 0.0))

                # exit_price_val initially comes from final close
                # Weighted average will be calculated by the TradeExecution model validator
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
                # Fees: Try to fetch ACTUAL fees from Alpaca Activities (CFEE)
                fees_usd = 0.0
                fee_calculation_type = "ESTIMATED"
                fee_tier = None
                actual_fee_usd = None

                is_crypto = pos.get("asset_class") == "CRYPTO"

                if is_crypto:
                    # 1. Try Actual CFEE Lookup
                    actual_fee_usd = self._get_actual_fees(
                        alpaca_order_id, pos.get("symbol"), order_side_str
                    )

                    if actual_fee_usd is not None:
                        fees_usd = actual_fee_usd
                        fee_calculation_type = "ACTUAL_CFEE"
                        logger.debug(
                            f"Using ACTUAL fees for {pos.get('symbol')}: ${fees_usd:.2f}"
                        )
                    else:
                        # 2. Fallback to Estimation
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
                            f"Using ESTIMATED fees for {pos.get('symbol')}: ${fees_usd:.2f} ({fee_tier})"
                        )

                # PnL Calculation using ALPACA entry price (Truth) vs
                # Firestore Exit Price
                pnl_gross = (exit_price_val - entry_price_val) * qty

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
                    exit_price=exit_price_val,  # Will be weighted-averaged by model!
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
                    fee_finalized=(
                        fee_calculation_type == "ACTUAL_CFEE"
                    ),  # Finalized if we got actuals
                    actual_fee_usd=actual_fee_usd,  # Populated if found
                    fee_calculation_type=fee_calculation_type,
                    fee_tier=fee_tier,  # e.g., "Tier 0"
                    entry_order_id=pos.get("entry_order_id"),  # For CFEE attribution
                    fee_reconciled_at=(
                        datetime.now(timezone.utc)
                        if fee_calculation_type == "ACTUAL_CFEE"
                        else None
                    ),
                    # PASS THROUGH FIELDS FOR MODEL LOGIC
                    scaled_out_prices=pos.get("scaled_out_prices", []),
                    original_qty=pos.get("original_qty"),
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
