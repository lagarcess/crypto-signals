from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from crypto_signals.config import Settings
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.market.data_provider import MarketDataProvider, memory


@pytest.fixture
def mock_clients():
    stock_client = Mock()
    crypto_client = Mock()
    return stock_client, crypto_client


def test_memory_location_is_none_by_default():
    """
    Regression Test: Ensure joblib memory location is None by default.
    critical for production safety.
    """
    assert memory.location is None


def test_routing_disabled_by_default(mock_clients):
    """Test that requests route to _fetch_bars_core when caching is disabled (default)."""
    stock_client, crypto_client = mock_clients
    provider = MarketDataProvider(stock_client, crypto_client)

    with (
        patch("crypto_signals.market.data_provider._fetch_bars_core") as mock_core,
        patch("crypto_signals.market.data_provider._fetch_bars_cached") as mock_cached,
    ):
        provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)

        mock_core.assert_called_once()
        mock_cached.assert_not_called()

        # Verify call args
        args, kwargs = mock_core.call_args
        assert kwargs["symbol"] == "AAPL"
        assert kwargs["cache_key"] == "no-cache"


def test_routing_enabled_uses_cache(mock_clients):
    """Test that requests use MarketDataCache when enabled."""
    stock_client, crypto_client = mock_clients

    # Enable caching setting
    with patch("crypto_signals.market.data_provider.get_settings") as mock_settings:
        mock_settings.return_value = Settings(ENABLE_MARKET_DATA_CACHE=True)
        provider = MarketDataProvider(stock_client, crypto_client)

        with (
            patch("crypto_signals.market.data_provider._fetch_bars_core") as mock_core,
            patch("crypto_signals.market.data_provider.datetime", wraps=datetime) as mock_datetime,
        ):
            # Mock time for stable cache key
            fixed_now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = fixed_now
            mock_datetime.strptime.side_effect = datetime.strptime

            # Mock cache return value
            # Ensure index is DatetimeIndex
            mock_df = pd.DataFrame({"close": [100]}, index=pd.to_datetime([fixed_now]))
            provider.cache.get_monthly_bars = Mock(return_value=mock_df)

            res = provider.get_daily_bars("BTC/USD", AssetClass.CRYPTO, lookback_days=5)

            assert res is not None
            assert not res.empty
            provider.cache.get_monthly_bars.assert_called()
