"""Tests for the MarketDataProvider module."""

from unittest.mock import Mock

import pandas as pd
import pytest
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.timeframe import TimeFrame

from crypto_signals.domain.schemas import AssetClass
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.market.exceptions import MarketDataError


@pytest.fixture
def mock_stock_client():
    """Mock stock historical data client."""
    return Mock(spec=StockHistoricalDataClient)


@pytest.fixture
def mock_crypto_client():
    """Mock crypto historical data client."""
    return Mock(spec=CryptoHistoricalDataClient)


@pytest.fixture
def provider(mock_stock_client, mock_crypto_client):
    """Fixture for MarketDataProvider with mocked clients."""
    return MarketDataProvider(mock_stock_client, mock_crypto_client)


def test_init(mock_stock_client, mock_crypto_client):
    """Test initialization of MarketDataProvider."""
    provider = MarketDataProvider(mock_stock_client, mock_crypto_client)
    assert provider.stock_client == mock_stock_client
    assert provider.crypto_client == mock_crypto_client


def test_get_daily_bars_equity_success(provider, mock_stock_client):
    """Test fetching equity bars proxies to stock client correctly."""
    # Setup
    mock_bars = Mock()
    # Mock dataframe response
    df_data = {"close": [150.0, 155.0]}
    df = pd.DataFrame(df_data)
    mock_bars.df = df
    mock_stock_client.get_stock_bars.return_value = mock_bars

    # Exec
    result = provider.get_daily_bars("AAPL", AssetClass.EQUITY, lookback_days=10)

    # Verify
    assert result.equals(df)
    mock_stock_client.get_stock_bars.assert_called_once()
    call_args = mock_stock_client.get_stock_bars.call_args[0][0]
    assert call_args.symbol_or_symbols == "AAPL"
    # Compare TimeFrame properties as object equality might fail
    assert call_args.timeframe.amount == TimeFrame.Day.amount
    assert call_args.timeframe.unit == TimeFrame.Day.unit
    assert call_args.adjustment == "split"


def test_get_daily_bars_crypto_success(provider, mock_crypto_client):
    """Test fetching crypto bars proxies to crypto client correctly."""
    # Setup
    mock_bars = Mock()
    df_data = {"close": [50000.0, 51000.0]}
    df = pd.DataFrame(df_data)
    mock_bars.df = df
    mock_crypto_client.get_crypto_bars.return_value = mock_bars

    # Exec
    result = provider.get_daily_bars("BTC/USD", AssetClass.CRYPTO)

    # Verify
    assert result.equals(df)
    mock_crypto_client.get_crypto_bars.assert_called_once()
    call_args = mock_crypto_client.get_crypto_bars.call_args[0][0]
    assert call_args.symbol_or_symbols == "BTC/USD"
    assert call_args.timeframe.amount == TimeFrame.Day.amount
    assert call_args.timeframe.unit == TimeFrame.Day.unit


def test_get_daily_bars_empty_error(provider, mock_stock_client):
    """Test that empty dataframe raises MarketDataError."""
    mock_bars = Mock()
    mock_bars.df = pd.DataFrame()  # Empty
    mock_stock_client.get_stock_bars.return_value = mock_bars

    with pytest.raises(MarketDataError, match="No daily bars found"):
        provider.get_daily_bars("AAPL", AssetClass.EQUITY)


def test_get_daily_bars_api_error(provider, mock_stock_client):
    """Test API failure raises MarketDataError."""
    mock_stock_client.get_stock_bars.side_effect = Exception("API Down")

    with pytest.raises(MarketDataError, match="Failed to fetch"):
        provider.get_daily_bars("AAPL", AssetClass.EQUITY)


def test_get_latest_price_equity(provider, mock_stock_client):
    """Test fetching latest equity price."""
    # Setup
    mock_trade_response = {"AAPL": Mock(price=150.50)}
    mock_stock_client.get_stock_latest_trade.return_value = mock_trade_response

    # Exec
    price = provider.get_latest_price("AAPL", AssetClass.EQUITY)

    # Verify
    assert price == 150.50
    mock_stock_client.get_stock_latest_trade.assert_called_once()


def test_get_latest_price_crypto(provider, mock_crypto_client):
    """Test fetching latest crypto price."""
    # Setup
    mock_trade_response = {"BTC/USD": Mock(price=60000.00)}
    mock_crypto_client.get_crypto_latest_trade.return_value = mock_trade_response

    # Exec
    price = provider.get_latest_price("BTC/USD", AssetClass.CRYPTO)

    # Verify
    assert price == 60000.00
    mock_crypto_client.get_crypto_latest_trade.assert_called_once()


def test_invalid_asset_class(provider):
    """Test checking invalid asset class."""
    # Using a string to bypass enumeration check if type checker allowed,
    # or just mocking a weird enum if needed, but Python allows passing 'FOO'.
    # usually, or just rely on type checker.
    # Let's pass a string "COMMODITY" to trigger 'Unsupported asset class'
    with pytest.raises(MarketDataError, match="Unsupported asset class"):
        provider.get_latest_price("GOLD", "COMMODITY")  # type: ignore
