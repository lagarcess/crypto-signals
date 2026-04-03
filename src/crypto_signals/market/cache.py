"""
Market Data Caching Layer.

Provides local and remote (Supabase) caching for historical market data.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.repository.supabase_storage import SupabaseStorageRepository


class MarketDataCache:
    """
    Cache layer for market data, using local storage and Supabase Storage.
    """

    def __init__(self):
        """
        Initialize the cache with storage repositories.
        """
        settings = get_settings()
        self.bucket_name = settings.SUPABASE_MARKET_DATA_BUCKET
        self.storage = SupabaseStorageRepository(self.bucket_name)

        # Local cache path: .gemini/cache/market_data/
        self.local_root = settings.project_root / ".gemini" / "cache" / "market_data"

    def get_path_taxonomy(self, asset_class: AssetClass, symbol: str, timeframe: str, year_month: str) -> str:
        """
        Build the standardized path taxonomy.

        Args:
            asset_class: CRYPTO or EQUITY
            symbol: Ticker symbol (standardized, e.g. BTC_USD)
            timeframe: e.g. 1Day, 1Hour
            year_month: e.g. 2024_01

        Returns:
            str: Path in the bucket.
        """
        # Standardize symbol (replace / with _ for file systems/buckets)
        safe_symbol = symbol.replace("/", "_")
        return f"{asset_class.value}/{safe_symbol}/{timeframe}/{year_month}.parquet"

    def get_monthly_bars(self, symbol: str, asset_class: AssetClass, year_month: str) -> Optional[pd.DataFrame]:
        """
        Try to get bars for a specific month from cache.

        Args:
            symbol: Ticker symbol
            asset_class: Asset class
            year_month: e.g. 2024_01

        Returns:
            Optional[pd.DataFrame]: DataFrame if found, else None.
        """
        remote_path = self.get_path_taxonomy(asset_class, symbol, "1Day", year_month)
        local_path = self.local_root / remote_path

        # 1. Check local cache
        if local_path.exists():
            try:
                return pd.read_parquet(local_path)
            except Exception as e:
                logger.error(f"Error reading local parquet cache: {e}")

        # 2. Check remote cache (Supabase)
        if self.storage.download_file(remote_path, local_path):
            try:
                return pd.read_parquet(local_path)
            except Exception as e:
                logger.error(f"Error reading downloaded parquet cache: {e}")

        return None

    def save_monthly_bars(self, symbol: str, asset_class: AssetClass, year_month: str, df: pd.DataFrame) -> bool:
        """
        Save bars for a specific month to cache.

        Args:
            symbol: Ticker symbol
            asset_class: Asset class
            year_month: e.g. 2024_01
            df: DataFrame to save.

        Returns:
            bool: True if successful, False otherwise.
        """
        remote_path = self.get_path_taxonomy(asset_class, symbol, "1Day", year_month)
        local_path = self.local_root / remote_path
        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Save locally
            df.to_parquet(local_path, engine="pyarrow", compression="snappy")

            # Upload to remote if the month is finalized (not the current month)
            current_month = datetime.now(timezone.utc).strftime("%Y_%m")
            if year_month < current_month:
                self.storage.upload_file(local_path, remote_path)
            else:
                logger.debug(f"Skipping remote upload for current month: {year_month}")

            return True
        except Exception as e:
            logger.error(f"Error saving bars to cache: {e}")
            return False

    def get_range_partitioned(self, start_dt: datetime, end_dt: datetime) -> list[str]:
        """
        Partition a date range into year_month strings.

        Args:
            start_dt: Start datetime
            end_dt: End datetime

        Returns:
            list[str]: List of year_month strings (e.g. ["2024_01", "2024_02"])
        """
        months = pd.date_range(
            start=start_dt.replace(day=1),
            end=end_dt,
            freq="MS"
        ).strftime("%Y_%m").tolist()
        return months
