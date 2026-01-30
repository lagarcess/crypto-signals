"""
Rejected Signal Archival Pipeline.

This pipeline moves expired/processed rejected signals from Firestore (Operational)
to BigQuery (Analytical) for filter tuning and theoretical performance analysis.

Pattern: Extract-Transform-Load
1. Extract: Get rejected signals from Firestore
2. Transform: Calculate theoretical P&L based on actual market prices
3. Load: Push to BigQuery via BasePipeline
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pandas as pd
from google.cloud import firestore
from loguru import logger
from pydantic import BaseModel

from crypto_signals.config import (
    get_crypto_data_client,
    get_settings,
    get_stock_data_client,
)
from crypto_signals.domain.schemas import FactRejectedSignal, OrderSide
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.pipelines.base import BigQueryPipelineBase

# Crypto fee constant (0.25% taker fee for base tier)
CRYPTO_TAKER_FEE_PCT = 0.0025


class RejectedSignalArchival(BigQueryPipelineBase):
    """
    Pipeline to archive rejected signals from Firestore to BigQuery.

    Calculates theoretical P&L by checking if signals would have hit
    their take profit or stop loss targets.
    """

    def __init__(self):
        """Initialize the pipeline with specific configuration."""
        settings = get_settings()
        env_suffix = "" if settings.ENVIRONMENT == "PROD" else "_test"

        super().__init__(
            job_name="rejected_signal_archival",
            staging_table_id=(
                f"{settings.GOOGLE_CLOUD_PROJECT}.crypto_analytics.stg_rejected_signals{env_suffix}"
            ),
            fact_table_id=(
                f"{settings.GOOGLE_CLOUD_PROJECT}.crypto_analytics.fact_rejected_signals{env_suffix}"
            ),
            id_column="signal_id",
            partition_column="ds",
            schema_model=FactRejectedSignal,
        )

        # Initialize Source Clients
        self.firestore_client = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        self.source_collection = (
            "rejected_signals"
            if settings.ENVIRONMENT == "PROD"
            else "test_rejected_signals"
        )

        # Initialize MarketDataProvider for theoretical P&L
        stock_client = get_stock_data_client()
        crypto_client = get_crypto_data_client()
        self.market_provider = MarketDataProvider(stock_client, crypto_client)

    def extract(self) -> List[Any]:
        """
        Extract rejected signals ready for archival.

        Only extracts signals older than 7 days to ensure enough market data
        for theoretical P&L calculation.
        """
        logger.info(f"[{self.job_name}] extracting rejected signals from Firestore...")

        # Get signals older than 7 days
        settings = get_settings()
        validity_window = timedelta(days=settings.TTL_DAYS_DEV)
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - validity_window

        docs = (
            self.firestore_client.collection(self.source_collection)
            .where(field_path="created_at", op_string="<", value=cutoff)
            .limit(100)  # Process in batches
            .stream()
        )

        raw_data = []
        for doc in docs:
            data = doc.to_dict()
            if data:
                data["_doc_id"] = doc.id  # Preserve doc ID for cleanup
                raw_data.append(data)

        logger.info(f"[{self.job_name}] extracted {len(raw_data)} rejected signals.")
        return raw_data

    def transform(self, raw_data: List[Any]) -> List[Dict[str, Any]]:
        """
        Calculate theoretical P&L for rejected signals.

        Checks if the signal would have hit TP or SL based on actual market data.
        """
        logger.info(
            f"[{self.job_name}] Calculating theoretical P&L for {len(raw_data)} signals..."
        )

        transformed = []

        for signal in raw_data:
            try:
                symbol = signal.get("symbol")
                asset_class = signal.get("asset_class", "CRYPTO")
                entry_price = float(signal.get("entry_price", 0))
                stop_loss = float(signal.get("suggested_stop", 0))
                take_profit_1 = float(signal.get("take_profit_1") or 0)
                side = signal.get("side", OrderSide.BUY.value)
                created_at = signal.get("created_at")

                if not all([symbol, entry_price, stop_loss, take_profit_1]):
                    logger.warning(
                        f"Skipping signal {signal.get('signal_id')}: missing fields"
                    )
                    continue

                # Market Data Fetching Bypass for Validation Failures
                rejection_reason = signal.get("rejection_reason", "")
                is_validation_failure = (
                    rejection_reason and "VALIDATION_FAILED" in rejection_reason
                )

                if is_validation_failure:
                    # Logic Skip: Do not fetch market data.
                    # Rationale: Validation failures often have invalid parameters (stop=0)
                    # or happen on assets where data might be questionable.
                    # We just archive the failure record with neutral Stats.
                    bars_df = pd.DataFrame()  # Empty
                    logger.info(
                        f"Skipping market data for validation failure: {signal.get('signal_id')}"
                    )
                else:
                    # Fetch market data since signal creation
                    bars_df = self.market_provider.get_daily_bars(
                        symbol=symbol,
                        asset_class=asset_class,
                        lookback_days=30,
                    )

                    if bars_df.empty:
                        logger.warning(f"No market data for {symbol}")
                        continue

                    # Filter bars after signal creation
                    if created_at:
                        bars_df = bars_df[
                            bars_df.index >= pd.Timestamp(created_at).floor("D")
                        ]

                # Determine theoretical exit
                exit_price = None
                exit_reason = None
                exit_time = None

                if is_validation_failure:
                    exit_reason = "VALIDATION_FAILED_NO_EXECUTION"
                    pnl_net = 0.0
                    pnl_pct = 0.0
                    total_fees = 0.0
                    exit_time = created_at
                else:
                    # Standard Theoretical Simulation Loop
                    for idx, bar in bars_df.iterrows():
                        high = float(bar["high"])
                        low = float(bar["low"])

                        if side == OrderSide.BUY.value:
                            # Long: check if TP1 hit (high >= TP1) or SL hit (low <= SL)
                            if high >= take_profit_1:
                                exit_price = take_profit_1
                                exit_reason = "THEORETICAL_TP1"
                                exit_time = idx
                                break
                            elif low <= stop_loss:
                                exit_price = stop_loss
                                exit_reason = "THEORETICAL_SL"
                                exit_time = idx
                                break
                        else:
                            # Short: check if TP1 hit (low <= TP1) or SL hit (high >= SL)
                            if low <= take_profit_1:
                                exit_price = take_profit_1
                                exit_reason = "THEORETICAL_TP1"
                                exit_time = idx
                                break
                            elif high >= stop_loss:
                                exit_price = stop_loss
                                exit_reason = "THEORETICAL_SL"
                                exit_time = idx
                                break

                    # If no exit triggered, use latest close as theoretical exit
                    if exit_price is None and not is_validation_failure:
                        exit_price = float(bars_df.iloc[-1]["close"])
                        exit_reason = "THEORETICAL_OPEN"
                        exit_time = bars_df.index[-1]

                    # Calculate theoretical P&L
                    qty = 1.0  # Normalized unit calculation
                    if not is_validation_failure:
                        if side == OrderSide.BUY.value:
                            pnl_gross = (exit_price - entry_price) * qty
                        else:
                            pnl_gross = (entry_price - exit_price) * qty

                        # Calculate fees (crypto: 0.25% each way)
                        entry_fee = entry_price * qty * CRYPTO_TAKER_FEE_PCT
                        exit_fee = exit_price * qty * CRYPTO_TAKER_FEE_PCT
                        total_fees = entry_fee + exit_fee

                        pnl_net = pnl_gross - total_fees
                        pnl_pct = (
                            (pnl_net / (entry_price * qty)) * 100 if entry_price else 0
                        )

                # Build record
                record = {
                    "doc_id": signal.get("_doc_id"),  # Fix #174: Map preserved doc ID
                    "ds": created_at.date()
                    if hasattr(created_at, "date")
                    else created_at,
                    "signal_id": signal.get("signal_id"),
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "pattern_name": signal.get("pattern_name"),
                    "rejection_reason": signal.get("rejection_reason"),
                    "trade_type": "VALIDATION_FAILED"
                    if is_validation_failure
                    else "FILTERED",
                    "side": side,
                    "entry_price": entry_price,
                    "suggested_stop": stop_loss,
                    "take_profit_1": take_profit_1,
                    "theoretical_exit_price": exit_price,
                    "theoretical_exit_reason": exit_reason,
                    "theoretical_exit_time": exit_time.isoformat()
                    if exit_time is not None
                    else None,
                    "theoretical_pnl_usd": round(pnl_net, 4),
                    "theoretical_pnl_pct": round(pnl_pct, 4),
                    "theoretical_fees_usd": round(total_fees, 6),
                    "created_at": created_at.isoformat()
                    if created_at is not None
                    else str(created_at),
                }

                model = self.schema_model.model_validate(record)
                transformed.append(model.model_dump(mode="json"))

            except Exception as e:
                logger.error(
                    f"Failed to transform rejected signal {signal.get('signal_id')}: {e}"
                )
                continue

        logger.info(
            f"[{self.job_name}] transformed {len(transformed)} signals with theoretical P&L."
        )
        return transformed

    def cleanup(self, data: list[BaseModel]) -> None:
        """
        Delete processed rejected signals from Firestore.

        Args:
            data: List of successfully loaded data dicts.
        """
        if not data:
            return

        logger.info(
            f"[{self.job_name}] Cleaning up {len(data)} records from Firestore..."
        )

        batch = self.firestore_client.batch()
        count = 0

        for item in data:
            # Fix #174: Use explicit doc_id if available (FactRejectedSignal), else fallback to signal_id
            doc_id = getattr(item, "doc_id", None) or getattr(item, "signal_id", None)

            if not doc_id:
                continue
            ref = self.firestore_client.collection(self.source_collection).document(
                str(doc_id)
            )
            batch.delete(ref)
            count += 1

            if count >= 400:
                batch.commit()
                batch = self.firestore_client.batch()
                count = 0

        if count > 0:
            batch.commit()

        logger.info(f"[{self.job_name}] Cleanup complete.")
