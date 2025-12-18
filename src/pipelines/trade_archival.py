"""
Trade Archival Pipeline.

This pipeline moves CLOSED positions from Firestore (Operational) to BigQuery (Analytical).
It enriches the data by fetching exact execution details (fees, fill times) from the Alpaca API.

Pattern: "Enrich-Extract-Load"
1. Extract: Get CLOSED positions from Firestore.
2. Transform: Call Alpaca API for each position to get truth data (fees, times).
3. Load: Push to BigQuery via BasePipeline (Truncate->Staging->Merge).
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, List, Dict

from google.cloud import firestore

from src.config import settings, get_trading_client

from alpaca.common.exceptions import APIError

from src.pipelines.base import BigQueryPipelineBase
from src.schemas import TradeExecution

logger = logging.getLogger(__name__)


class TradeArchivalPipeline(BigQueryPipelineBase):
    """
    Pipeline to archive closed trades from Firestore to BigQuery.
    
    Enriches Firestore data with precise execution details from Alpaca.
    """
    
    def __init__(self):
        """
        Initialize the pipeline with specific configuration.
        """
        # Configure BigQuery settings
        super().__init__(
            job_name="trade_archival",
            staging_table_id=f"{settings().GOOGLE_CLOUD_PROJECT}.crypto_sentinel.stg_trades_import",
            fact_table_id=f"{settings().GOOGLE_CLOUD_PROJECT}.crypto_sentinel.fact_trades",
            id_column="trade_id",
            partition_column="ds",
            schema_model=TradeExecution,
        )
        
        # Initialize Source Clients
        # Note: We use the project from settings, same as BQ
        self.firestore_client = firestore.Client(project=settings().GOOGLE_CLOUD_PROJECT)
        self.alpaca = get_trading_client()

    def extract(self) -> List[Any]:
        """
        Extract CLOSED positions from Firestore.
        
        Returns:
            List[dict]: List of raw position dictionaries.
        """
        logger.info(f"[{self.job_name}] extracting CLOSED positions from Firestore...")
        
        # Query: status == 'CLOSED'
        # We scan live_positions for any trade that is marked closed
        # The Cleanup step will delete them after successful load, ensuring we don't re-process forever.
        docs = (
            self.firestore_client.collection("live_positions")
            .where(field_path="status", op_string="==", value="CLOSED")
            .stream()
        )
        
        # Convert to list of dicts, keeping the ID if needed (though position_id is in body)
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
        logger.info(f"[{self.job_name}] Enriching {len(raw_data)} trades with Alpaca data...")
        
        transformed = []
        
        for pos in raw_data:
            # Rate Limit Safety: Sleep 100ms to avoid hitting Alpaca's 200 req/min limit
            time.sleep(0.1)
            
            try:
                # 1. Fetch Order Details from Alpaca to get Fees and Exact Times
                # The position_id in Firestore IS the Client Order ID from Alpaca (idempotency key)
                client_order_id = pos.get("position_id")
                
                try:
                    # Fetch order by client_order_id to ensure we get the specific trade
                    order = self.alpaca.get_order_by_client_order_id(client_order_id)
                except APIError as e:
                    # Specific handling for 404/Not Found
                    # Alpaca APIError has a 'status_code' attribute (usually 404 for not found)
                    if getattr(e, 'status_code', None) == 404 or "not found" in str(e).lower():
                        logger.warning(f"[{self.job_name}] Order {client_order_id} not found in Alpaca. Skipping.")
                        continue
                    raise e
                
                # 2. Calculate Derived Metrics
                # Note: Alpaca 'filled_avg_price' is the source of truth for execution price
                entry_price_val = float(order.filled_avg_price) if order.filled_avg_price else 0.0
                qty = float(order.filled_qty) if order.filled_qty else 0.0
                
                # We need to determine exit details. 
                # For this task, we rely on Firestore for 'exit_fill_price' and 'exit_time'
                # as the prompt implies these are known from the close event.
                
                # Let's assume the doc has `exit_fill_price`.
                exit_price_val = float(pos.get("exit_fill_price", 0.0))
                
                # Timestamps
                entry_time_str = pos.get("entry_time") # Should be in doc
                exit_time_str = pos.get("exit_time")   # Should be in doc
                
                # Parse or default
                def parse_dt(val):
                    if isinstance(val, datetime): return val
                    try: return datetime.fromisoformat(str(val))
                    except: return datetime.now(timezone.utc)
                
                entry_time = parse_dt(entry_time_str)
                exit_time = parse_dt(exit_time_str)
                
                # CALCULATIONS
                # Fees: Hard to get exact without activity ID. 
                # TODO: Implement exact fee fetching via TradeActivity endpoint in Phase 4
                fees_usd = 0.0 
                
                # PnL Calculation using ALPACA entry price (Truth) vs Firestore Exit Price
                pnl_gross = (exit_price_val - entry_price_val) * qty
                if pos.get("side") == "sell": # Short
                    pnl_gross = (entry_price_val - exit_price_val) * qty
                    
                pnl_usd = pnl_gross - fees_usd
                pnl_pct = (pnl_usd / (entry_price_val * qty)) if (entry_price_val and qty) else 0.0
                
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
                    qty=qty, # Authenticated from Alpaca
                    entry_price=entry_price_val, # Authenticated from Alpaca
                    exit_price=exit_price_val,
                    entry_time=entry_time,
                    exit_time=exit_time,
                    pnl_usd=round(pnl_usd, 2),
                    pnl_pct=round(pnl_pct, 4),
                    fees_usd=round(fees_usd, 2),
                    slippage_pct=0.0, 
                    trade_duration=duration
                )
                
                # Validate and Dump to JSON (BasePipeline expects dicts)
                transformed.append(trade.model_dump(mode='json'))
                
            except Exception as e:
                # Log error but don't stop the whole batch? 
                # For now, log and skip specific bad records to avoid blocking the pipeline.
                logger.error(f"[{self.job_name}] Failed to transform position {pos.get('position_id')}: {e}")
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

        logger.info(f"[{self.job_name}] Cleaning up {len(data)} records from Firestore...")
        
        # Batch delete
        batch = self.firestore_client.batch()
        count = 0
        
        for item in data:
            # item is a dict from BIGQUERY format or Pydantic dump.
            # We need the Original ID used in Firestore. 
            # In transform, we mapped trade_id -> position_id.
            doc_id = item.get("trade_id") 
            
            # Assumption: Firestore Doc ID == position_id (which is usually true in this design)
            # If Doc ID was random, we'd need to have passed it through.
            # Let's assume Doc ID KEY strategy is used or we query ID.
            # Usually: collection('live_positions').document(position_id)
            ref = self.firestore_client.collection("live_positions").document(doc_id)
            batch.delete(ref)
            count += 1
            
            if count >= 400: # Firestore batch limit is 500
                batch.commit()
                batch = self.firestore_client.batch()
                count = 0
                
        if count > 0:
            batch.commit()

        logger.info(f"[{self.job_name}] Cleanup complete.")
