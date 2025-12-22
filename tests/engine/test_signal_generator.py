"""Unit tests for the SignalGenerator module."""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest
from crypto_signals.domain.schemas import (
    AssetClass,
    ExitReason,
    Signal,
    SignalStatus,
)
from crypto_signals.engine.signal_generator import SignalGenerator


@pytest.fixture
def mock_market_provider():
    """Fixture for mocking the MarketDataProvider."""
    return MagicMock()


@pytest.fixture
def mock_indicators():
    """Fixture for mocking TechnicalIndicators."""
    mock = MagicMock()
    # Mock add_all_indicators to return the DataFrame unchanged
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
    assert signal.strategy_id == "BULLISH_ENGULFING"
    # Engulfing invalidation is Open (100.0). Stop is 100.0 * 0.99 = 99.0
    assert signal.suggested_stop == 100.0 * 0.99
    assert signal.asset_class == AssetClass.CRYPTO
    assert signal.entry_price == 105.0  # Close price from df


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
    assert signal.asset_class == AssetClass.EQUITY
    assert signal.entry_price == 105.0


def test_generate_signal_priority(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that Bullish Engulfing is prioritized over Bullish Hammer."""
    # Setup Data: BOTH patterns are True
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [100.0],
            "volume": [1000.0],
        },
        index=[pd.Timestamp("2023-01-01")],
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


def test_generate_signal_none(signal_generator, mock_market_provider, mock_analyzer_cls):
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

    assert signal is None

    assert signal is None


def test_check_exits_profit_hit_tp1_scaling(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test detecting a Take Profit 1 hit (Scaling)."""
    # Setup Active Signal
    signal = Signal(
        signal_id="sig_1",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=90.0,
        status=SignalStatus.WAITING,
        take_profit_1=110.0,
        take_profit_2=120.0,
        invalidation_price=90.0,
    )

    # Setup Market Data (Hit TP1)
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [115.0],  # Hit 110
            "low": [95.0],
            "close": [105.0],
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )
    # Passed via dataframe argument, so provider shouldn't be called if logic is correct

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(exited) == 1
    assert exited[0].status == SignalStatus.TP1_HIT
    # Stop should be moved to Breakeven
    assert exited[0].suggested_stop == 100.0
    assert exited[0].exit_reason == ExitReason.TP1

    # Ensure provider was NOT called because we passed dataframe
    mock_market_provider.get_daily_bars.assert_not_called()


def test_check_exits_invalidation(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test detecting a Structural Invalidation."""
    # Setup Active Signal
    signal = MagicMock()
    signal.take_profit_1 = 120.0
    signal.take_profit_2 = None
    signal.invalidation_price = 95.0
    signal.status = SignalStatus.WAITING

    # Setup Market Data (Close below invalidation)
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [102.0],
            "low": [90.0],
            "close": [92.0],  # Below 95
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )
    mock_market_provider.get_daily_bars.return_value = df

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    exited = signal_generator.check_exits([signal], "BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert len(exited) == 1
    assert exited[0].status == SignalStatus.INVALIDATED


def test_check_exits_none(signal_generator, mock_market_provider, mock_analyzer_cls):
    """Test no exit triggered."""
    # Setup Active Signal
    signal = MagicMock()
    signal.take_profit_1 = 120.0
    signal.take_profit_2 = None
    signal.invalidation_price = 90.0
    signal.status = SignalStatus.WAITING

    # Setup Market Data (Normal day)
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [105.0],
            "low": [98.0],
            "close": [102.0],
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )
    mock_market_provider.get_daily_bars.return_value = df

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    exited = signal_generator.check_exits([signal], "BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert len(exited) == 0


def test_check_exits_runner_exit(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test detecting a Runner Exit (Chandelier Exit)."""
    # Setup Active Signal (TP2 already hit, now in Runner mode)
    signal = Signal(
        signal_id="sig_2",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=110.0,
        status=SignalStatus.TP2_HIT,
        take_profit_1=110.0,
        take_profit_2=120.0,
        invalidation_price=90.0,
    )

    # Setup Market Data (Close BELOW Chandelier Exit)
    # Price > Entry (Win) but < Chandelier
    df = pd.DataFrame(
        {
            "open": [130.0],
            "high": [135.0],
            "low": [125.0],
            "close": [128.0],
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_LONG": [129.0],  # Exit Trigger
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(exited) == 1
    assert exited[0].status == SignalStatus.TP3_HIT
    assert exited[0].exit_reason == ExitReason.TP_HIT

    signal.take_profit_1 = 104.0
    signal.take_profit_2 = 110.0
    signal.entry_price = 100.0
    signal.status = SignalStatus.WAITING

    # Setup Market Data (Hit TP1)
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [105.0],  # Hit TP1
            "low": [98.0],
            "close": [102.0],
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_market_provider.get_daily_bars.return_value = df
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution (pass dataframe)
    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(exited) == 1
    assert exited[0].status == SignalStatus.TP1_HIT
    assert exited[0].suggested_stop == 100.0  # Breakeven
    assert exited[0].exit_reason == ExitReason.TP1
