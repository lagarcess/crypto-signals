"""
Tests for MarketDataCache.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.market.cache import MarketDataCache


@pytest.fixture
def cache():
    with patch("crypto_signals.market.cache.get_settings") as mock_settings:
        mock_settings.return_value.SUPABASE_MARKET_DATA_BUCKET = "test_bucket"
        mock_settings.return_value.project_root = Path("/tmp")
        return MarketDataCache()


def test_path_taxonomy(cache):
    """Test standardized path taxonomy generation."""
    path = cache.get_path_taxonomy(AssetClass.CRYPTO, "BTC/USD", "1Day", "2024_01")
    assert path == "CRYPTO/BTC_USD/1Day/2024_01.parquet"

    path = cache.get_path_taxonomy(AssetClass.EQUITY, "AAPL", "1Day", "2024_02")
    assert path == "EQUITY/AAPL/1Day/2024_02.parquet"


def test_get_range_partitioned(cache):
    """Test date range partitioning into months."""
    start_dt = datetime(2023, 12, 15, tzinfo=timezone.utc)
    end_dt = datetime(2024, 2, 10, tzinfo=timezone.utc)

    months = cache.get_range_partitioned(start_dt, end_dt)
    assert months == ["2023_12", "2024_01", "2024_02"]


@patch("pandas.read_parquet")
def test_get_monthly_bars_local_hit(mock_read, cache):
    """Test cache hit from local storage."""
    mock_df = pd.DataFrame({"close": [100]})
    mock_read.return_value = mock_df

    with patch.object(Path, "exists", return_value=True):
        res = cache.get_monthly_bars("BTC/USD", AssetClass.CRYPTO, "2024_01")
        assert res is not None
        assert res.equals(mock_df)
        mock_read.assert_called_once()


@patch("pandas.read_parquet")
def test_get_monthly_bars_remote_hit(mock_read, cache):
    """Test cache hit from remote storage (Supabase)."""
    mock_df = pd.DataFrame({"close": [100]})
    mock_read.return_value = mock_df

    cache.storage.download_file = MagicMock(return_value=True)

    with patch.object(Path, "exists", return_value=False):
        res = cache.get_monthly_bars("BTC/USD", AssetClass.CRYPTO, "2024_01")
        assert res is not None
        assert res.equals(mock_df)
        cache.storage.download_file.assert_called_once()


def test_save_monthly_bars_finalized(cache):
    """Test saving a finalized month (uploads to remote)."""
    df = pd.DataFrame({"close": [100]})
    cache.storage.upload_file = MagicMock(return_value=True)

    # Mock current month to be later than the month being saved
    fixed_now = datetime(2024, 3, 1, tzinfo=timezone.utc)
    with patch("crypto_signals.market.cache.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now

        with patch.object(pd.DataFrame, "to_parquet"):
            cache.save_monthly_bars("BTC/USD", AssetClass.CRYPTO, "2024_01", df)
            cache.storage.upload_file.assert_called_once()


def test_save_monthly_bars_current(cache):
    """Test saving the current month (skips remote upload)."""
    df = pd.DataFrame({"close": [100]})
    cache.storage.upload_file = MagicMock(return_value=True)

    # Mock current month to be the same as the month being saved
    fixed_now = datetime(2024, 1, 15, tzinfo=timezone.utc)
    with patch("crypto_signals.market.cache.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now

        with patch.object(pd.DataFrame, "to_parquet"):
            cache.save_monthly_bars("BTC/USD", AssetClass.CRYPTO, "2024_01", df)
            cache.storage.upload_file.assert_not_called()
