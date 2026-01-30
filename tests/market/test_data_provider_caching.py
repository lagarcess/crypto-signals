
from unittest.mock import Mock

import pandas as pd
import pytest
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.market.data_provider import MarketDataProvider, memory


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
    return MarketDataProvider(*mock_clients)

@pytest.fixture(autouse=True)
def clear_cache():
    memory.clear(warn=False)
    yield
    memory.clear(warn=False)

def test_get_daily_bars_caching(provider, mock_clients):
    """
    Test that get_daily_bars caches results.
    """
    stock_client, _ = mock_clients

    # Run 1
    result1 = provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
    assert not result1.empty
    # Should be called once
    assert stock_client.get_stock_bars.call_count == 1

    # Run 2 - Should use cache
    stock_client.get_stock_bars.reset_mock()
    result2 = provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
    assert result2.equals(result1)

    # Expectation: Not called again
    assert stock_client.get_stock_bars.call_count == 0


def test_cache_invalidation_on_params(provider, mock_clients):
    """Test that changing parameters triggers new fetch."""
    stock_client, _ = mock_clients

    provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)
    assert stock_client.get_stock_bars.call_count == 1
    stock_client.get_stock_bars.reset_mock()

    # Change symbol
    provider.get_daily_bars("MSFT", AssetClass.EQUITY, lookback_days=10)
    # Should be called again
    assert stock_client.get_stock_bars.call_count == 1
