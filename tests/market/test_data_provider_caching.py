
import pytest
import shutil
import pandas as pd
from unittest.mock import Mock, patch
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.market.data_provider import MarketDataProvider, memory
from crypto_signals.config import Settings
import joblib

@pytest.fixture
def mock_clients():
    stock_client = Mock()
    crypto_client = Mock()

    # Setup default responses
    df_data = {"close": [150.0, 155.0]}
    mock_bars = Mock()
    mock_bars.df = pd.DataFrame(df_data, index=pd.to_datetime(["2023-01-01", "2023-01-02"]))

    stock_client.get_stock_bars.return_value = mock_bars
    crypto_client.get_crypto_bars.return_value = mock_bars

    return stock_client, crypto_client

@pytest.fixture
def provider(mock_clients):
    # Default behavior: Caching disabled (as per default config)
    # We will override this in specific tests
    return MarketDataProvider(*mock_clients)

@pytest.fixture(autouse=True)
def clear_cache():
    memory.clear(warn=False)
    yield
    memory.clear(warn=False)

def test_caching_disabled_by_default(provider, mock_clients):
    """Test that caching is disabled by default via config."""
    from crypto_signals.config import get_settings

    settings = get_settings()
    # Should be False by default
    assert settings.ENABLE_MARKET_DATA_CACHE is False

    stock_client, _ = mock_clients

    # Call twice
    provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
    provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)

    # Should call API twice (no caching)
    assert stock_client.get_stock_bars.call_count == 2


def test_caching_enabled(mock_clients):
    """Test that caching works when enabled."""
    stock_client, _ = mock_clients

    # Mock settings to enable caching
    with patch('crypto_signals.market.data_provider.get_settings') as mock_settings:
        mock_settings.return_value = Settings(ENABLE_MARKET_DATA_CACHE=True)

        provider = MarketDataProvider(*mock_clients)

        # Run 1
        result1 = provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
        assert stock_client.get_stock_bars.call_count == 1

        # Run 2
        result2 = provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
        assert result2.equals(result1)

        # Count should still be 1
        assert stock_client.get_stock_bars.call_count == 1

def test_cache_invalidation_on_params(mock_clients):
    """Test that changing parameters triggers new fetch when caching enabled."""
    stock_client, _ = mock_clients

    with patch('crypto_signals.market.data_provider.get_settings') as mock_settings:
        mock_settings.return_value = Settings(ENABLE_MARKET_DATA_CACHE=True)
        provider = MarketDataProvider(*mock_clients)

        provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
        assert stock_client.get_stock_bars.call_count == 1

        # Change symbol
        provider.get_daily_bars("MSFT", AssetClass.EQUITY, lookback_days=10)
        assert stock_client.get_stock_bars.call_count == 2

def test_cache_invalidation_on_date_change(mock_clients):
    """Test that cache invalidates when date changes (TTL)."""
    stock_client, _ = mock_clients

    with patch('crypto_signals.market.data_provider.get_settings') as mock_settings:
        mock_settings.return_value = Settings(ENABLE_MARKET_DATA_CACHE=True)
        provider = MarketDataProvider(*mock_clients)

        # Run 1 - Day 1
        with patch('crypto_signals.market.data_provider.datetime') as mock_datetime:
            mock_datetime.now.return_value = pd.Timestamp("2023-01-01 10:00:00", tz="UTC")
            # We need to forward timedelta as well since we mocked datetime
            mock_datetime.timedelta = pd.Timedelta

            provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
            assert stock_client.get_stock_bars.call_count == 1

            # Run 2 - Same Day
            provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
            assert stock_client.get_stock_bars.call_count == 1

            # Run 3 - Next Day
            mock_datetime.now.return_value = pd.Timestamp("2023-01-02 10:00:00", tz="UTC")
            provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
            assert stock_client.get_stock_bars.call_count == 2
