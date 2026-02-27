"""Unit tests for the SignalGenerator module."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from crypto_signals.analysis.structural import Pivot
from crypto_signals.domain.schemas import (
    AssetClass,
    ExitReason,
    OrderSide,
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
def mock_repository():
    """Fixture for mocking SignalRepository."""
    mock = MagicMock()
    mock.get_most_recent_exit.return_value = None
    return mock


@pytest.fixture
def signal_generator(
    mock_market_provider, mock_indicators, mock_analyzer_cls, mock_repository
):
    """Fixture for creating a SignalGenerator instance with mocks."""
    with patch("crypto_signals.repository.firestore.PositionRepository") as mock_pos_repo:
        mock_pos_repo_instance = mock_pos_repo.return_value
        mock_pos_repo_instance.get_open_position_by_symbol.return_value = None
        
        return SignalGenerator(
            market_provider=mock_market_provider,
            indicators=mock_indicators,
            pattern_analyzer_cls=mock_analyzer_cls,
            signal_repo=mock_repository,
        )


@pytest.fixture
def chandelier_exit_df(mock_analyzer_cls):
    """Single-row OHLCV + indicators DataFrame + mock analyzer setup for chandelier exit tests."""
    df = pd.DataFrame(
        {
            "open": [110.0],
            "high": [115.0],
            "low": [105.0],
            "close": [108.0],
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_LONG": [112.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    return df


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
        valid_until=datetime.now(timezone.utc) + timedelta(hours=24),
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
    signal.valid_until = datetime.now(timezone.utc) + timedelta(hours=24)
    signal.created_at = None  # Skip cooldown gate in check_exits

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
    signal.valid_until = datetime.now(timezone.utc) + timedelta(hours=24)
    signal.created_at = None  # Skip cooldown gate in check_exits

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
    signal.valid_until = datetime.now(timezone.utc) + timedelta(hours=24)

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


def test_check_exits_no_waiting_tp3_jump(
    signal_generator, mock_market_provider, chandelier_exit_df
):
    """Verify WAITING signal is NOT marked TP3_HIT when close < chandelier (Issue 123)."""
    # Setup Active Signal in WAITING status
    signal = Signal(
        signal_id="sig_waiting",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=90.0,
        status=SignalStatus.WAITING,
        take_profit_1=150.0,  # Far away
        take_profit_2=200.0,
        invalidation_price=80.0,
        created_at=None,
    )

    df = chandelier_exit_df

    # Execution
    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification: Currently BUGGY, it will return TP3_HIT.
    # We want it to be empty (no exit triggered).
    assert len(exited) == 0


def test_check_exits_tp1_to_tp3_hit(
    signal_generator, mock_market_provider, chandelier_exit_df
):
    """Verify TP1_HIT signal correctly transitions to TP3_HIT (Issue 123)."""
    # Setup Active Signal in TP1_HIT status
    signal = Signal(
        signal_id="sig_tp1",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=100.0,
        status=SignalStatus.TP1_HIT,
        take_profit_1=110.0,
        take_profit_2=200.0,
        invalidation_price=80.0,
        created_at=None,
    )

    df = chandelier_exit_df

    # Execution
    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(exited) == 1
    assert exited[0].status == SignalStatus.TP3_HIT


def test_check_exits_tp2_to_tp3_hit(
    signal_generator, mock_market_provider, chandelier_exit_df
):
    """Verify TP2_HIT signal correctly transitions to TP3_HIT (Issue 123)."""
    # Setup Active Signal in TP2_HIT status
    signal = Signal(
        signal_id="sig_tp2",
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
        invalidation_price=80.0,
        created_at=None,
    )

    df = chandelier_exit_df

    # Execution
    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(exited) == 1
    assert exited[0].status == SignalStatus.TP3_HIT


def test_check_exits_stale_waiting_signal_regression(
    signal_generator, mock_market_provider, chandelier_exit_df
):
    """Regression: 288h-old WAITING signal does not phantom-trigger TP3 (Issue 123)."""
    # Setup Active Signal in WAITING status, created 288 hours ago
    now_utc = datetime.now(timezone.utc)
    signal = Signal(
        signal_id="sig_stale",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=90.0,
        status=SignalStatus.WAITING,
        take_profit_1=150.0,
        take_profit_2=200.0,
        invalidation_price=80.0,
        created_at=now_utc - timedelta(hours=288),
    )

    df = chandelier_exit_df

    # Execution
    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification: Should be empty
    assert len(exited) == 0


def test_check_exits_trail_update_higher(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that take_profit_3 is updated when Chandelier Exit moves higher."""
    # Setup Active Signal in Runner phase (TP1_HIT)
    signal = Signal(
        signal_id="sig_trail_1",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=100.0,  # At breakeven
        status=SignalStatus.TP1_HIT,
        take_profit_1=110.0,
        take_profit_2=120.0,
        take_profit_3=115.0,  # Current trailing stop
        invalidation_price=90.0,
    )

    # Setup Market Data: Chandelier Exit is HIGHER than current TP3
    # Price is still above Chandelier (no exit triggered)
    # High is BELOW TP2 (120) to avoid status change
    df = pd.DataFrame(
        {
            "open": [118.0],
            "high": [119.0],  # Below TP2 (120) - no status change
            "low": [116.0],
            "close": [118.0],  # Above Chandelier Exit (120 < 118 is FALSE, wait...)
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_LONG": [
                117.0
            ],  # Higher than current TP3 (115), close (118) > this
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    result = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(result) == 1
    assert result[0].take_profit_3 == 117.0  # Updated to new Chandelier Exit
    assert hasattr(result[0], "_trail_updated")
    assert result[0]._trail_updated is True
    assert hasattr(result[0], "_previous_tp3")
    assert result[0]._previous_tp3 == 115.0  # Previous value stored
    # Status should NOT have changed
    assert result[0].status == SignalStatus.TP1_HIT


def test_check_exits_trail_not_updated_when_lower(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that take_profit_3 is NOT updated when Chandelier Exit is lower."""
    # Setup Active Signal in Runner phase (TP2_HIT)
    signal = Signal(
        signal_id="sig_trail_2",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=100.0,
        status=SignalStatus.TP2_HIT,
        take_profit_1=110.0,
        take_profit_2=120.0,
        take_profit_3=125.0,  # Current trailing stop
        invalidation_price=90.0,
    )

    # Setup Market Data: Chandelier Exit is LOWER than current TP3
    df = pd.DataFrame(
        {
            "open": [130.0],
            "high": [135.0],
            "low": [128.0],
            "close": [132.0],  # Above Chandelier Exit (no exit)
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_LONG": [120.0],  # Lower than current TP3 (125)
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    result = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification: No signals should be returned (no exit, no trail update)
    assert len(result) == 0
    # Original signal should still have original TP3
    assert signal.take_profit_3 == 125.0


def test_check_exits_trail_not_updated_for_waiting_status(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that trailing updates only apply to TP1_HIT and TP2_HIT statuses."""
    # Setup Active Signal in WAITING status (not in Runner phase yet)
    signal = Signal(
        signal_id="sig_trail_3",
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
        take_profit_3=105.0,  # Initial TP3
        invalidation_price=90.0,
        valid_until=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    # Setup Market Data: Chandelier Exit is higher but status is WAITING
    # Close is ABOVE Chandelier to avoid TP3 exit trigger
    # High is BELOW TP1 to avoid TP1 hit
    df = pd.DataFrame(
        {
            "open": [102.0],
            "high": [109.0],  # Below TP1 (110) - no TP1 trigger
            "low": [100.0],
            "close": [109.0],  # Above Chandelier Exit (108) - no TP3 exit
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_LONG": [108.0],  # Higher than TP3 (105)
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    result = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification: No exit, no trail update (WAITING status doesn't get trailing)
    assert len(result) == 0
    assert signal.take_profit_3 == 105.0  # Unchanged


# =============================================================================
# SHORT POSITION TRAILING STOP TESTS
# =============================================================================


def test_check_exits_short_trail_update_lower(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that Short position take_profit_3 is updated when Chandelier Exit moves LOWER."""
    # Setup Active SHORT SHORT Signal in Runner phase (TP1_HIT)
    signal = Signal(
        signal_id="sig_short_trail_1",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,  # Shorted at $100
        pattern_name="TEST",
        suggested_stop=110.0,  # Stop loss ABOVE entry for short
        status=SignalStatus.TP1_HIT,
        take_profit_1=90.0,  # TP1 for short is BELOW entry
        take_profit_2=80.0,
        take_profit_3=95.0,  # Current trailing stop (above current price)
        invalidation_price=None,  # Avoid Long-biased invalidation check triggering
        side=OrderSide.SELL,  # SHORT position
    )

    # Setup Market Data: Chandelier Exit Short is LOWER than current TP3
    df = pd.DataFrame(
        {
            "open": [85.0],
            "high": [87.0],
            "low": [82.0],
            "close": [85.0],  # BELOW entry (Profit) and ABOVE Chandelier Short (No exit)
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_SHORT": [88.0],  # Lower than current TP3 (95)
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    result = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(result) == 1
    assert (
        result[0].take_profit_3 == 88.0
    )  # Updated to new (lower) Chandelier Exit Short
    assert result[0]._trail_updated is True
    assert result[0]._previous_tp3 == 95.0


def test_check_exits_short_trail_not_updated_when_higher(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that Short position take_profit_3 is NOT updated when Chandelier Exit is HIGHER."""
    # Setup Active SHORT Signal in Runner phase (TP2_HIT)
    signal = Signal(
        signal_id="sig_short_trail_2",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        side=OrderSide.SELL,
        entry_price=100.0,
        status=SignalStatus.TP2_HIT,
        take_profit_3=80.0,  # Current trailing stop
        invalidation_price=None,
    )

    # Setup Market Data: Chandelier Exit is HIGHER than current TP3
    df = pd.DataFrame(
        {
            "open": [75.0],
            "high": [78.0],
            "low": [72.0],
            "close": [75.0],
            "CHANDELIER_EXIT_SHORT": [85.0],  # Higher than current TP3 (80)
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    result = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(result) == 0
    assert signal.take_profit_3 == 80.0  # Unchanged


def test_check_exits_short_tp3_hit(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test detecting a Short position Take Profit 3 hit."""
    # Setup Active SHORT Signal in Runner phase
    signal = Signal(
        signal_id="sig_short_tp3",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        side=OrderSide.SELL,
        entry_price=100.0,
        status=SignalStatus.TP2_HIT,
        take_profit_3=80.0,
        invalidation_price=None,
    )

    # Setup Market Data: Price crosses ABOVE Chandelier Exit Short
    df = pd.DataFrame(
        {
            "open": [85.0],
            "high": [92.0],
            "low": [84.0],
            "close": [90.0],  # Above Chandelier (88)
            "CHANDELIER_EXIT_SHORT": [88.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    result = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification
    assert len(result) == 1
    assert result[0].status == SignalStatus.TP3_HIT
    assert result[0].exit_reason == ExitReason.TP_HIT


def test_check_exits_stale_short_waiting_regression(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Regression: 288h-old SHORT WAITING signal does not phantom-trigger TP3."""
    now_utc = datetime.now(timezone.utc)
    signal = Signal(
        signal_id="sig_stale_short",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        side=OrderSide.SELL,
        entry_price=100.0,
        status=SignalStatus.WAITING,
        take_profit_1=80.0,
        take_profit_2=70.0,
        created_at=now_utc - timedelta(hours=288),
    )

    # Market data that would trigger TP3 if not for WAITING status
    df = pd.DataFrame(
        {
            "open": [95.0],
            "high": [105.0],
            "low": [94.0],
            "close": [102.0],  # Above Chandelier Short (98)
            "CHANDELIER_EXIT_SHORT": [98.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    result = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification: Should be empty
    assert len(result) == 0
