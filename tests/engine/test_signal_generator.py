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
    # Setup Active SHORT Signal in Runner phase (TP1_HIT)
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
    # Price is still below Chandelier (no exit triggered for short)
    # IMPORTANT: For Short TP test isolation:
    # - low must be > take_profit_2 (80) to avoid directional TP2 trigger
    # - close must be < chandelier_exit_short (92) to avoid TP3 exit
    # - close must be < invalidation_price (if set) to avoid Short invalidation
    df = pd.DataFrame(
        {
            "open": [85.0],
            "high": [88.0],
            "low": [82.0],  # Above take_profit_2 (80) - no Short TP2 trigger
            "close": [85.0],  # Below Chandelier Exit Short (92) - no TP3 exit
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_LONG": [80.0],  # Not used for short
            "CHANDELIER_EXIT_SHORT": [92.0],  # Lower than current TP3 (95)
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
    assert result[0].take_profit_3 == 92.0  # Updated to new (lower) Chandelier Exit
    assert hasattr(result[0], "_trail_updated")
    assert result[0]._trail_updated is True
    assert hasattr(result[0], "_previous_tp3")
    assert result[0]._previous_tp3 == 95.0  # Previous value stored
    assert result[0].status == SignalStatus.TP1_HIT  # Status unchanged


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
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=110.0,
        status=SignalStatus.TP2_HIT,
        take_profit_1=90.0,
        take_profit_2=80.0,
        take_profit_3=85.0,  # Current trailing stop
        invalidation_price=None,  # Avoid Long-biased invalidation check
        side=OrderSide.SELL,  # SHORT position
    )

    # Setup Market Data: Chandelier Exit Short is HIGHER than current TP3
    # For shorts, higher stop is unfavorable (would lock in less profit)
    # IMPORTANT: For Short TP test isolation:
    # - low must be > take_profit_2 (80) to avoid directional TP2 trigger
    df = pd.DataFrame(
        {
            "open": [82.0],
            "high": [84.0],
            "low": [81.0],  # Above take_profit_2 (80) - no Short TP2 trigger
            "close": [83.0],  # Below Chandelier (no exit)
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_LONG": [78.0],
            "CHANDELIER_EXIT_SHORT": [88.0],  # Higher than current TP3 (85) - unfavorable
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
    assert signal.take_profit_3 == 85.0  # Unchanged


def test_check_exits_short_trail_initialization(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that Short position initializes trailing stop when current TP3 is 0."""
    # Setup Active SHORT Signal in Runner phase with NO trailing stop yet
    signal = Signal(
        signal_id="sig_short_trail_3",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=110.0,
        status=SignalStatus.TP1_HIT,
        take_profit_1=90.0,
        take_profit_2=80.0,
        take_profit_3=None,  # No trailing stop set yet
        invalidation_price=None,  # Avoid Long-biased invalidation check
        side=OrderSide.SELL,  # SHORT position
    )

    # Setup Market Data: First Chandelier Exit value to initialize
    # IMPORTANT: For Short TP test isolation:
    # - low must be > take_profit_2 (80) to avoid directional TP2 trigger
    # - close must be < chandelier_exit_short (93) to avoid TP3 exit
    df = pd.DataFrame(
        {
            "open": [85.0],
            "high": [87.0],
            "low": [82.0],  # Above take_profit_2 (80) - no Short TP2 trigger
            "close": [85.0],  # Below Chandelier Exit Short (93) - no TP3 exit
            "volume": [1000.0],
            "bearish_engulfing": [False],
            "RSI_14": [50.0],
            "ADX_14": [20.0],
            "CHANDELIER_EXIT_LONG": [80.0],
            "CHANDELIER_EXIT_SHORT": [93.0],  # Initial trailing stop value
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

    # Verification: Should initialize trailing stop
    assert len(result) == 1
    assert result[0].take_profit_3 == 93.0  # Initialized to Chandelier Exit Short
    assert hasattr(result[0], "_trail_updated")
    assert result[0]._trail_updated is True
    assert result[0]._previous_tp3 == 0.0  # Previous was None/0


def test_generate_signal_harmonic_and_geometric_merging(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test merging of harmonic (ABCD) and geometric (Bull Flag) patterns on same candle.

    Multi-Layer Architecture: When both patterns occur:
    - Geometric pattern is the tactical trigger (pattern_name)
    - Harmonic pattern is structural context (structural_context field)
    - Single signal is created (no duplicate)
    - harmonic_metadata is populated with ratios
    - conviction_tier is HIGH
    """
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

    # Mock Analyzer Instance
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    # Result DF with BOTH Bull Flag (geometric) pattern
    result_df = df.copy()
    result_df["bull_flag"] = True
    result_df["bullish_engulfing"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df

    # Mock pivots for harmonic analysis
    # Create 4 pivots for ABCD pattern
    mock_pivots = [
        Pivot(
            price=95.0,
            timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
            pivot_type="VALLEY",
            index=0,
        ),
        Pivot(
            price=105.0,
            timestamp=datetime(2023, 1, 5, tzinfo=timezone.utc),
            pivot_type="PEAK",
            index=1,
        ),
        Pivot(
            price=98.0,
            timestamp=datetime(2023, 1, 10, tzinfo=timezone.utc),
            pivot_type="VALLEY",
            index=2,
        ),
        Pivot(
            price=108.0,
            timestamp=datetime(2023, 1, 15, tzinfo=timezone.utc),
            pivot_type="PEAK",
            index=3,
        ),
    ]
    mock_analyzer_instance.pivots = mock_pivots

    # Mock HarmonicAnalyzer to return ABCD pattern
    mock_harmonic_pattern = MagicMock()
    mock_harmonic_pattern.pattern_type = "ABCD"
    mock_harmonic_pattern.ratios = {"AB_CD_price_ratio": 1.0, "AB_CD_time_ratio": 1.0}

    with patch(
        "crypto_signals.engine.signal_generator.HarmonicAnalyzer"
    ) as mock_harmonic_cls:
        mock_harmonic_instance = MagicMock()
        mock_harmonic_instance.scan_all_patterns.return_value = [mock_harmonic_pattern]
        mock_harmonic_cls.return_value = mock_harmonic_instance

        # Execution
        signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is not None, "Signal should be generated"

    # 1. Geometric pattern is the tactical trigger (Multi-Layer Architecture)
    assert (
        signal.pattern_name == "BULL_FLAG"
    ), "Pattern name should be BULL_FLAG (geometric)"

    # 2. Harmonic context stored in structural_context
    assert (
        signal.structural_context == "ABCD"
    ), "structural_context should be ABCD (harmonic)"

    # 3. Conviction tier is HIGH (tactical + structural)
    assert signal.conviction_tier == "HIGH", "conviction_tier should be HIGH"

    # 4. Single signal (implicit - we only get one signal back)
    assert signal.symbol == "BTC/USD"

    # 5. Harmonic metadata is populated
    assert signal.harmonic_metadata is not None, "harmonic_metadata should be populated"
    assert (
        "AB_CD_price_ratio" in signal.harmonic_metadata
    ), "Should have AB_CD_price_ratio"
    assert "AB_CD_time_ratio" in signal.harmonic_metadata, "Should have AB_CD_time_ratio"


def test_generate_signal_harmonic_only(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that harmonic-only detection (no geometric) returns None.

    Multi-Layer Architecture: Structural context alone doesn't produce
    an entry signal — a tactical trigger (geometric pattern) is required.
    """
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

    # Mock Analyzer Instance
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    # Result DF with NO geometric patterns
    result_df = df.copy()
    result_df["bull_flag"] = False
    result_df["bullish_engulfing"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df

    # Mock pivots for harmonic analysis
    mock_pivots = [
        Pivot(
            price=95.0,
            timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
            pivot_type="VALLEY",
            index=0,
        ),
        Pivot(
            price=105.0,
            timestamp=datetime(2023, 1, 5, tzinfo=timezone.utc),
            pivot_type="PEAK",
            index=1,
        ),
        Pivot(
            price=98.0,
            timestamp=datetime(2023, 1, 10, tzinfo=timezone.utc),
            pivot_type="VALLEY",
            index=2,
        ),
        Pivot(
            price=108.0,
            timestamp=datetime(2023, 1, 15, tzinfo=timezone.utc),
            pivot_type="PEAK",
            index=3,
        ),
    ]
    mock_analyzer_instance.pivots = mock_pivots

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification: No signal â€” harmonic-only doesn't produce an entry
    assert (
        signal is None
    ), "Harmonic-only should not generate a signal (Multi-Layer Architecture)"


def test_generate_signal_harmonic_macro_classification(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that MACRO_PATTERN classification is applied when harmonic pattern is_macro.

    Multi-Layer Architecture: Geometric trigger required. Harmonic macro context
    sets pattern_classification to MACRO_PATTERN (not MACRO_HARMONIC).
    """
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

    # Mock Analyzer Instance
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    # Result DF with geometric pattern (required for signal generation)
    result_df = df.copy()
    result_df["bull_flag"] = True
    mock_analyzer_instance.check_patterns.return_value = result_df

    # Mock pivots for MACRO harmonic pattern (>90 days)
    # ABCD pattern spanning 100 days
    base_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
    mock_pivots = [
        Pivot(
            price=95.0,
            timestamp=base_date,
            pivot_type="VALLEY",
            index=0,
        ),
        Pivot(
            price=105.0,
            timestamp=base_date + timedelta(days=30),
            pivot_type="PEAK",
            index=1,
        ),
        Pivot(
            price=98.0,
            timestamp=base_date + timedelta(days=60),
            pivot_type="VALLEY",
            index=2,
        ),
        Pivot(
            price=108.0,
            timestamp=base_date + timedelta(days=100),
            pivot_type="PEAK",
            index=3,
        ),
    ]
    mock_analyzer_instance.pivots = mock_pivots

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is not None, "Signal should be generated"
    assert signal.pattern_name == "BULL_FLAG", "Pattern name should be geometric trigger"
    assert (
        signal.pattern_classification == "MACRO_PATTERN"
    ), "Classification should be MACRO_PATTERN for macro harmonic context"
    assert signal.structural_context == "ABCD", "Structural context should be ABCD"
    assert signal.conviction_tier == "HIGH", "Should be HIGH conviction"


# =============================================================================
# SIGNAL LIFECYCLE HARDENING TESTS (Issue 99)
# Tests for 5-minute cooldown gate, dynamic TTL, and Elliott Wave ATR stop loss
# =============================================================================


def test_check_exits_cooldown_gate_skips_newly_created_signal(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that signals created within 5 minutes are skipped by check_exits (Issue 99)."""
    # Setup Active Signal created 2 minutes ago (120 seconds < 300s cooldown)
    now_utc = datetime.now(timezone.utc)
    signal = Signal(
        signal_id="sig_new",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=90.0,
        status=SignalStatus.WAITING,
        take_profit_1=110.0,
        invalidation_price=90.0,
        created_at=now_utc - timedelta(seconds=120),  # 2 minutes ago
        valid_until=now_utc + timedelta(hours=24),
    )

    # Setup Market Data that would normally trigger invalidation
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [102.0],
            "low": [85.0],
            "close": [88.0],  # Below invalidation_price (90.0)
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

    # Verification: Signal should be skipped due to cooldown gate
    assert len(exited) == 0, "Signal should be skipped during cooldown period"


def test_check_exits_cooldown_gate_processes_after_cooldown(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that signals older than 5 minutes are processed normally (Issue 99)."""
    # Setup Active Signal created 6 minutes ago (360 seconds > 300s cooldown)
    now_utc = datetime.now(timezone.utc)
    signal = Signal(
        signal_id="sig_old",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=90.0,
        status=SignalStatus.WAITING,
        take_profit_1=110.0,
        invalidation_price=90.0,
        created_at=now_utc - timedelta(seconds=360),  # 6 minutes ago
        valid_until=now_utc + timedelta(hours=24),
    )

    # Setup Market Data that triggers invalidation
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [102.0],
            "low": [85.0],
            "close": [88.0],  # Below invalidation_price (90.0)
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

    # Verification: Signal should be processed and invalidated
    assert len(exited) == 1, "Signal should be processed after cooldown"
    assert exited[0].status == SignalStatus.INVALIDATED


def test_generate_signal_dynamic_ttl_standard_pattern(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that STANDARD patterns get 48h TTL (Issue 99)."""
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

    # Result DF with bullish_engulfing pattern
    result_df = df.copy()
    result_df["bullish_engulfing"] = True
    result_df["bullish_hammer"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df
    mock_analyzer_instance.pivots = []  # No harmonic pattern

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is not None
    # STANDARD pattern should get 48h TTL
    candle_timestamp = pd.Timestamp(today).to_pydatetime().replace(tzinfo=timezone.utc)
    expected_valid_until = candle_timestamp + timedelta(hours=48)
    assert signal.valid_until == expected_valid_until


def test_generate_signal_dynamic_ttl_macro_pattern(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that MACRO patterns get 120h TTL (Issue 99).

    Multi-Layer Architecture: Needs geometric trigger + macro harmonic context.
    """
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

    # Result DF with geometric pattern (required for signal generation)
    result_df = df.copy()
    result_df["bull_flag"] = True
    result_df["bullish_engulfing"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df

    # Mock pivots for MACRO harmonic pattern (>90 days)
    base_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
    mock_pivots = [
        Pivot(
            price=95.0,
            timestamp=base_date,
            pivot_type="VALLEY",
            index=0,
        ),
        Pivot(
            price=105.0,
            timestamp=base_date + timedelta(days=30),
            pivot_type="PEAK",
            index=1,
        ),
        Pivot(
            price=98.0,
            timestamp=base_date + timedelta(days=60),
            pivot_type="VALLEY",
            index=2,
        ),
        Pivot(
            price=108.0,
            timestamp=base_date + timedelta(days=100),
            pivot_type="PEAK",
            index=3,
        ),
    ]
    mock_analyzer_instance.pivots = mock_pivots

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is not None
    # MACRO pattern should get 120h TTL
    candle_timestamp = pd.Timestamp(today).to_pydatetime().replace(tzinfo=timezone.utc)
    expected_valid_until = candle_timestamp + timedelta(hours=120)
    assert signal.valid_until == expected_valid_until
    assert signal.pattern_classification == "MACRO_PATTERN"


# =============================================================================
# ELLIOTT WAVE ATR-BASED STOP LOSS TESTS (Issue 99)
# =============================================================================


def test_generate_signal_elliott_wave_atr_stop_loss(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that Elliott Wave patterns use ATR-based stop loss (Issue 99)."""
    # Setup Data with ATR
    today = date(2023, 1, 1)
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [105.0],
            "volume": [1000.0],
            "ATR_14": [5.0],  # ATR = 5.0
        },
        index=[pd.Timestamp(today)],
    )
    mock_market_provider.get_daily_bars.return_value = df

    # Setup Pattern Analysis Result for Elliott Wave
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    result_df = df.copy()
    result_df["elliott_impulse_wave"] = True
    result_df["bullish_engulfing"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df
    mock_analyzer_instance.pivots = []  # No harmonic pattern

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is not None
    assert signal.pattern_name == "ELLIOTT_IMPULSE_WAVE"
    # Stop should be Low - (0.5 * ATR) = 90.0 - (0.5 * 5.0) = 87.5
    assert signal.suggested_stop == 87.5
    assert signal.invalidation_price == 90.0  # Low price


def test_generate_signal_elliott_wave_fallback_stop_loss(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Test that Elliott Wave patterns fall back to 1% stop when ATR is 0 (Issue 99)."""
    # Setup Data with ATR = 0
    today = date(2023, 1, 1)
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [105.0],
            "volume": [1000.0],
            "ATR_14": [0.0],  # ATR = 0.0 (edge case)
        },
        index=[pd.Timestamp(today)],
    )
    mock_market_provider.get_daily_bars.return_value = df

    # Setup Pattern Analysis Result for Elliott Wave
    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    result_df = df.copy()
    result_df["elliott_impulse_wave"] = True
    result_df["bullish_engulfing"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df
    mock_analyzer_instance.pivots = []  # No harmonic pattern

    # Execution
    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)

    # Verification
    assert signal is not None
    assert signal.pattern_name == "ELLIOTT_IMPULSE_WAVE"
    # Stop should fall back to Low * 0.99 = 90.0 * 0.99 = 89.1
    assert signal.suggested_stop == 89.1
    assert signal.invalidation_price == 90.0  # Low price


# ============================================================
# PHASE 2: Conviction-Aware Quality Gate Tests
# ============================================================


def _make_conviction_test_df(
    volume=1000.0,
    vol_sma_20=1000.0,
    adx=25.0,
    rsi=50.0,
    close=100.0,
    low=97.0,
    high=110.0,
    open_price=98.0,
    atr=5.0,
):
    """Helper to create a DataFrame with configurable indicator values for quality gate tests."""
    df = pd.DataFrame(
        {
            "open": [open_price],
            "high": [high],
            "low": [low],
            "close": [close],
            "volume": [volume],
            "VOL_SMA_20": [vol_sma_20],
            "ADX_14": [adx],
            "RSI_14": [rsi],
            "SMA_200": [80.0],
            "ATRr_14": [atr],
        },
        index=[pd.Timestamp("2023-01-01")],
    )
    return df


def _setup_harmonic_mocks(mock_analyzer_instance):
    """Setup mocks for harmonic pattern detection (pivots + HarmonicAnalyzer patch)."""
    from datetime import datetime, timezone

    from crypto_signals.analysis.structural import Pivot

    mock_pivots = [
        Pivot(
            price=95.0,
            timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
            pivot_type="VALLEY",
            index=0,
        ),
        Pivot(
            price=105.0,
            timestamp=datetime(2023, 1, 5, tzinfo=timezone.utc),
            pivot_type="PEAK",
            index=1,
        ),
        Pivot(
            price=98.0,
            timestamp=datetime(2023, 1, 10, tzinfo=timezone.utc),
            pivot_type="VALLEY",
            index=2,
        ),
        Pivot(
            price=108.0,
            timestamp=datetime(2023, 1, 15, tzinfo=timezone.utc),
            pivot_type="PEAK",
            index=3,
        ),
    ]
    mock_analyzer_instance.pivots = mock_pivots

    mock_harmonic_pattern = MagicMock()
    mock_harmonic_pattern.pattern_type = "GARTLEY"
    mock_harmonic_pattern.ratios = {"XA": 0.618}
    mock_harmonic_pattern.is_macro = False

    return mock_harmonic_pattern


def test_high_conviction_relaxes_volume_gate(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Volume 1.3x is rejected normally but passes with HIGH conviction (harmonic context)."""
    from unittest.mock import patch

    # Volume 1.3x < 1.5x threshold, but > 1.2x relaxed threshold
    df = _make_conviction_test_df(volume=1300.0, vol_sma_20=1000.0, adx=30.0)
    mock_market_provider.get_daily_bars.return_value = df

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    result_df = df.copy()
    result_df["bull_flag"] = True
    result_df["bullish_engulfing"] = False
    result_df["bull_flag_duration"] = 10
    result_df["bull_flag_classification"] = "STANDARD"
    mock_analyzer_instance.check_patterns.return_value = result_df

    # WITHOUT harmonic â†’ rejected (volume 1.3x < 1.5x)
    mock_analyzer_instance.pivots = []
    signal_no_harmonic = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)
    assert signal_no_harmonic is not None
    assert signal_no_harmonic.status == SignalStatus.REJECTED_BY_FILTER
    assert "Volume" in signal_no_harmonic.rejection_reason

    # WITH harmonic â†’ passes (volume 1.3x > 1.2x relaxed threshold)
    mock_harmonic_pattern = _setup_harmonic_mocks(mock_analyzer_instance)
    with patch(
        "crypto_signals.engine.signal_generator.HarmonicAnalyzer"
    ) as mock_harmonic_cls:
        mock_harmonic_instance = MagicMock()
        mock_harmonic_instance.scan_all_patterns.return_value = [mock_harmonic_pattern]
        mock_harmonic_cls.return_value = mock_harmonic_instance

        signal_with_harmonic = signal_generator.generate_signals(
            "BTC/USD", AssetClass.CRYPTO
        )

    assert signal_with_harmonic is not None
    assert signal_with_harmonic.status != SignalStatus.REJECTED_BY_FILTER
    assert signal_with_harmonic.conviction_tier == "HIGH"


def test_high_conviction_relaxes_adx_gate(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """ADX 17 is rejected normally but passes with HIGH conviction."""
    from unittest.mock import patch

    # ADX 17 < 20 threshold, but > 15 relaxed threshold
    # Use close/low values that produce good R:R so only ADX gate matters
    df = _make_conviction_test_df(
        volume=2000.0,
        vol_sma_20=1000.0,
        adx=17.0,
        close=100.0,
        low=97.0,
        high=110.0,
        open_price=98.0,
        atr=5.0,
    )
    mock_market_provider.get_daily_bars.return_value = df

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    result_df = df.copy()
    result_df["bull_flag"] = True
    result_df["bullish_engulfing"] = False
    result_df["bull_flag_duration"] = 10
    result_df["bull_flag_classification"] = "STANDARD"
    mock_analyzer_instance.check_patterns.return_value = result_df

    # WITHOUT harmonic â†’ rejected (ADX 17 < 20)
    mock_analyzer_instance.pivots = []
    signal_no_harmonic = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)
    assert signal_no_harmonic is not None
    assert signal_no_harmonic.status == SignalStatus.REJECTED_BY_FILTER
    assert "ADX" in signal_no_harmonic.rejection_reason

    # WITH harmonic â†’ passes (ADX 17 > 15 relaxed threshold)
    mock_harmonic_pattern = _setup_harmonic_mocks(mock_analyzer_instance)
    with patch(
        "crypto_signals.engine.signal_generator.HarmonicAnalyzer"
    ) as mock_harmonic_cls:
        mock_harmonic_instance = MagicMock()
        mock_harmonic_instance.scan_all_patterns.return_value = [mock_harmonic_pattern]
        mock_harmonic_cls.return_value = mock_harmonic_instance

        signal_with_harmonic = signal_generator.generate_signals(
            "BTC/USD", AssetClass.CRYPTO
        )

    assert signal_with_harmonic is not None
    assert signal_with_harmonic.status != SignalStatus.REJECTED_BY_FILTER
    assert signal_with_harmonic.conviction_tier == "HIGH"


def test_high_conviction_relaxes_rr_gate(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """R:R 1.3 is rejected normally but passes with HIGH conviction."""
    from unittest.mock import patch

    # close=100, low=93 â†’ stop=93*0.99=92.07, risk=7.93, TP1=110, profit=10 â†’ R:R=1.26 â€” in range
    df = _make_conviction_test_df(
        close=100.0,
        low=93.0,
        high=110.0,
        open_price=95.0,
        atr=5.0,
        volume=2000.0,
        vol_sma_20=1000.0,
        adx=30.0,
    )
    mock_market_provider.get_daily_bars.return_value = df

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    result_df = df.copy()
    result_df["bullish_hammer"] = True
    result_df["bullish_engulfing"] = False
    mock_analyzer_instance.check_patterns.return_value = result_df

    # WITHOUT harmonic â†’ rejected (R:R ~1.26 < 1.5)
    mock_analyzer_instance.pivots = []
    signal_no_harmonic = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)
    assert signal_no_harmonic is not None
    assert signal_no_harmonic.status == SignalStatus.REJECTED_BY_FILTER
    assert "R:R" in signal_no_harmonic.rejection_reason

    # WITH harmonic â†’ passes (R:R 1.26 > 1.2 relaxed threshold)
    mock_harmonic_pattern = _setup_harmonic_mocks(mock_analyzer_instance)
    with patch(
        "crypto_signals.engine.signal_generator.HarmonicAnalyzer"
    ) as mock_harmonic_cls:
        mock_harmonic_instance = MagicMock()
        mock_harmonic_instance.scan_all_patterns.return_value = [mock_harmonic_pattern]
        mock_harmonic_cls.return_value = mock_harmonic_instance

        signal_with_harmonic = signal_generator.generate_signals(
            "BTC/USD", AssetClass.CRYPTO
        )

    assert signal_with_harmonic is not None
    assert signal_with_harmonic.status != SignalStatus.REJECTED_BY_FILTER
    assert signal_with_harmonic.conviction_tier == "HIGH"


def test_standard_conviction_uses_normal_thresholds(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Without harmonic context, normal thresholds apply â€” no relaxation."""
    # Volume 1.3x < 1.5x â†’ rejected regardless (no harmonic)
    df = _make_conviction_test_df(volume=1300.0, vol_sma_20=1000.0, adx=30.0)
    mock_market_provider.get_daily_bars.return_value = df

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance

    result_df = df.copy()
    result_df["bull_flag"] = True
    result_df["bullish_engulfing"] = False
    result_df["bull_flag_duration"] = 10
    result_df["bull_flag_classification"] = "STANDARD"
    mock_analyzer_instance.check_patterns.return_value = result_df
    mock_analyzer_instance.pivots = []

    signal = signal_generator.generate_signals("BTC/USD", AssetClass.CRYPTO)
    assert signal is not None
    assert signal.status == SignalStatus.REJECTED_BY_FILTER
    assert signal.conviction_tier is None  # No harmonic = no conviction tier


def test_check_exits_skips_expired_waiting_signal(signal_generator, mock_analyzer_cls):
    """
    Verify that check_exits skips WAITING signals that are past their valid_until date (Issue #280).
    This is the defense-in-depth fix.
    """
    now_utc = datetime.now(timezone.utc)
    stale_valid_until = now_utc - timedelta(hours=1)

    # Setup Signal that is WAITING but EXPIRED
    signal = Signal(
        signal_id="stale_signal",
        ds=date.today() - timedelta(days=2),
        strategy_id="test_strat",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=90.0,
        status=SignalStatus.WAITING,
        take_profit_1=110.0,
        invalidation_price=95.0,
        valid_until=stale_valid_until,
        created_at=now_utc - timedelta(hours=2),  # Older than 5m cooldown
    )

    # Setup Market Data that would normally trigger INVALIDATED (price < invalidation_price)
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
        index=[pd.Timestamp(now_utc)],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    # Execution
    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification: Signal should be skipped and NOT returned in exited list
    # (Before fix, it would be returned as INVALIDATED)
    assert (
        len(exited) == 0
    ), "Stale WAITING signal should have been skipped by check_exits"
    assert (
        signal.status == SignalStatus.WAITING
    ), "Signal status should remain WAITING (skipped by generator)"


def test_check_exits_tp3_guard_waiting_signal(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Verify that a WAITING signal NEVER triggers a TP3 (Runner) exit,
    even if price hits the Chandelier Exit level (Issue #320)."""
    signal = Signal(
        signal_id="sig_waiting_tp3",
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

    # Market Data: Close < Chandelier Exit (would normally trigger Long TP3)
    # AND Close > Entry (profitable)
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
            "CHANDELIER_EXIT_LONG": [129.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    # Verification: Signal should NOT exit at TP3 (guard blocks it)
    # Because high=135 and TP1=110, it will trigger a TP1 exit on this candle instead.
    assert len(exited) == 1, "WAITING signal should have triggered normal TP exit"
    assert (
        exited[0].status != SignalStatus.TP3_HIT
    ), "WAITING signal incorrectly triggered TP3 exit"
    assert (
        exited[0].status == SignalStatus.TP1_HIT
    ), "Status should be TP1_HIT due to high > tp1"


def test_check_exits_tp3_guard_tp1_signal(
    signal_generator, mock_market_provider, mock_analyzer_cls
):
    """Verify that a TP1_HIT signal correctly triggers a TP3 (Runner) exit."""
    signal = Signal(
        signal_id="sig_tp1_tp3",
        ds=date(2023, 1, 1),
        strategy_id="strat_1",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=100.0,
        pattern_name="TEST",
        suggested_stop=110.0,
        status=SignalStatus.TP1_HIT,
        take_profit_1=110.0,
        take_profit_2=120.0,
        invalidation_price=90.0,
    )

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
            "CHANDELIER_EXIT_LONG": [129.0],
        },
        index=[pd.Timestamp("2023-01-02")],
    )

    mock_analyzer_instance = MagicMock()
    mock_analyzer_cls.return_value = mock_analyzer_instance
    mock_analyzer_instance.check_patterns.return_value = df

    exited = signal_generator.check_exits(
        [signal], "BTC/USD", AssetClass.CRYPTO, dataframe=df
    )

    assert len(exited) == 1, "TP1_HIT signal should have exited"
    assert exited[0].status == SignalStatus.TP3_HIT, "Status should be TP3_HIT"
    assert exited[0].exit_reason == ExitReason.TP_HIT
