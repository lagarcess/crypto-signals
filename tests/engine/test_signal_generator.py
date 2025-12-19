"""Unit tests for the SignalGenerator module."""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from crypto_signals.domain.schemas import AssetClass
from crypto_signals.engine.signal_generator import SignalGenerator
from crypto_signals.market.exceptions import MarketDataError


@pytest.fixture
def mock_market_provider():
    """Fixture for mocking the MarketDataProvider."""
    return MagicMock()


@pytest.fixture
def mock_indicators():
    """Fixture for mocking TechnicalIndicators."""
    mock = MagicMock()
    # Mock add_all_indicators to just return the dataframe
    mock.add_all_indicators.side_effect = lambda df: df
    return mock


@pytest.fixture
def mock_analyzer_cls():
    """Fixture for mocking the PatternAnalyzer class."""
    return MagicMock()


@pytest.fixture
def signal_generator(mock_market_provider, mock_indicators, mock_analyzer_cls):
    """Fixture for creating a SignalGenerator instance with mocks."""
    return SignalGenerator(
        market_provider=mock_market_provider,
        indicators=mock_indicators,
        pattern_analyzer_cls=mock_analyzer_cls,
    )


def test_generate_signal_bullish_engulfing(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that a signal is generated for a confirmed Bullish Engulfing pattern."""
    # Setup Data
    today = date(2023, 1, 1)
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [105.0],
            "volume": [1000.0],
        },
        index=[pd.Timestamp(today)],
    )
    mock_market_provider.get_daily_bars.return_value = df

    # Setup Pattern Analysis Result
    # Mock Analyzer Instance
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    # Result DF with patterns
    result_df = df.copy()
    result_df["bullish_engulfing"] = True
    result_df["bullish_hammer"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is not None
    assert signal.symbol == "BTC/USD"
    assert signal.pattern_name == "BULLISH_ENGULFING"
    assert signal.ds == today
    assert signal.strategy_id == "BULLISH_ENGULFING"
    assert signal.suggested_stop == 90.0 * 0.99


def test_generate_signal_bullish_hammer(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that a signal is generated for a confirmed Bullish Hammer pattern."""
    # Setup Data
    today = date(2023, 1, 1)
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [105.0],
            "volume": [1000.0],
        },
        index=[pd.Timestamp(today)],
    )
    mock_market_provider.get_daily_bars.return_value = df

    # Setup Pattern Analysis Result
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    # Result DF with patterns
    result_df = df.copy()
    result_df["bullish_engulfing"] = False
    result_df["bullish_hammer"] = True
    mock_analyzer_instance.check_patterns.return_value = result_df

    # Execution
    signal = signal_generator.generate_signals("AAPL", AssetClass.EQUITY)

    # Verification
    assert signal is not None
    assert signal.symbol == "AAPL"
    assert signal.pattern_name == "BULLISH_HAMMER"
    assert signal.strategy_id == "BULLISH_HAMMER"
    assert signal.ds == today
    assert signal.suggested_stop == 90.0 * 0.99


def test_generate_signal_priority(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that Bullish Engulfing is prioritized over Bullish Hammer."""
    # Setup Data: BOTH patterns are True
    df = pd.DataFrame(
        {"close": [100.0], "low": [90.0]}, index=[pd.Timestamp("2023-01-01")]
    )
    mock_market_provider.get_daily_bars.return_value = df

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    result_df = df.copy()
    result_df["bullish_engulfing"] = True
    result_df["bullish_hammer"] = True
    mock_analyzer_instance.check_patterns.return_value = result_df

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification: Engulfing should win
    assert signal is not None
    assert signal.pattern_name == "BULLISH_ENGULFING"


def test_generate_signal_none(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that None is returned when no patterns are detected."""
    # Setup Data: NO patterns
    df = pd.DataFrame(
        {"close": [100.0], "low": [90.0]}, index=[pd.Timestamp("2023-01-01")]
    )
    mock_market_provider.get_daily_bars.return_value = df

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    result_df = df.copy()
    result_df["bullish_engulfing"] = False
    result_df["bullish_hammer"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is None


def test_generate_signal_empty_data(signal_generator, mock_market_provider):
    """Test that None is returned when the market provider returns empty data."""
    # Setup Data: Empty DataFrame
    mock_market_provider.get_daily_bars.return_value = pd.DataFrame()

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is None


def test_generate_signal_market_data_error(signal_generator, mock_market_provider):
    """Test that MarketDataError is propagated when data fetching fails."""
    # Setup
    mock_market_provider.get_daily_bars.side_effect = MarketDataError("API Error")

    # Execution & Verification
    with pytest.raises(MarketDataError):
        signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)


def test_generate_signal_empty_analysis_result(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that None is returned when the analyzer result is empty."""
    # Setup
    df = pd.DataFrame({"close": [100.0]}, index=[pd.Timestamp("2023-01-01")])
    mock_market_provider.get_daily_bars.return_value = df

    # Mock Analyzer returning empty DataFrame
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = pd.DataFrame()

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is None
