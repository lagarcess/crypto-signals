"""Unit tests for the pattern analysis module."""

import pandas as pd
import pytest

from crypto_signals.analysis.patterns import PatternAnalyzer


@pytest.fixture
def mock_df():
    """Create a mock DataFrame for testing patterns."""
    # Create sufficient rows
    dates = pd.date_range(start="2023-01-01", periods=5, freq="h")
    df = pd.DataFrame(index=dates)

    # Initialize basic columns
    df["open"] = [100.0, 100.0, 100.0, 100.0, 100.0]
    df["high"] = [110.0, 110.0, 110.0, 110.0, 110.0]
    df["low"] = [90.0, 90.0, 90.0, 90.0, 90.0]
    df["close"] = [105.0, 105.0, 105.0, 105.0, 105.0]
    df["volume"] = [1000, 1000, 1000, 1000, 1000]

    # Indicator Columns required for Confluence
    # Trend: Price must be < EMA_50
    df["EMA_50"] = [120.0] * 5  # Downtrend context
    # Momentum: RSI < 45
    df["RSI_14"] = [40.0] * 5  # Oversold context
    # Volume: > 1.5 * SMA
    df["VOL_SMA_20"] = [1000.0] * 5  # Base volume

    return df


def test_bullish_hammer_detection(mock_df):
    """
    Test Row 2 (Index 2): Perfect Hammer.

    Conditions:
    - Lower Wick >= 2.0 * Body
    - Upper Wick <= 0.5 * Body
    - Volume Spike > 1.5x
    """
    # Setup Hammer at index 2
    # Body = 2 (100 to 102)
    # Lower Wick needs >= 4. Let's make it 5. Low = 100 - 5 = 95.
    # Upper Wick needs <= 1. Let's make it 0. High = 102.
    mock_df.loc[mock_df.index[2], "open"] = 100.0
    mock_df.loc[mock_df.index[2], "close"] = 102.0  # Body 2, Green
    mock_df.loc[mock_df.index[2], "low"] = 94.0  # Lower Wick = 6 (3x Body) -> OK
    mock_df.loc[mock_df.index[2], "high"] = 102.0  # Upper Wick = 0 -> OK

    # Add Volume Spike
    mock_df.loc[mock_df.index[2], "volume"] = 2000  # > 1.5 * 1000

    analyzer = PatternAnalyzer(mock_df)
    result = analyzer.check_patterns()

    assert result["bullish_hammer"].iloc[2], "Failed to detect valid Hammer"
    assert not result["bullish_hammer"].iloc[0], "False positive on normal candle"


def test_bullish_engulfing_detection(mock_df):
    """
    Test Row 4 (Index 4): Perfect Engulfing.

    Conditions:
    Index 3: Red Candle (small)
    Index 4: Green Candle (engulfs 3), Volume Spike
    """
    # Setup Previous Red Candle at index 3
    mock_df.loc[mock_df.index[3], "open"] = 102.0
    mock_df.loc[mock_df.index[3], "close"] = 100.0  # Red, Body 2

    # Setup Current Green Candle at index 4
    # Engulfs: Open <= 100, Close > 102
    mock_df.loc[mock_df.index[4], "open"] = 100.0
    mock_df.loc[mock_df.index[4], "close"] = 104.0  # Green, Body 4

    # Add Volume Spike
    mock_df.loc[mock_df.index[4], "volume"] = 2000

    analyzer = PatternAnalyzer(mock_df)
    result = analyzer.check_patterns()

    assert result["bullish_engulfing"].iloc[4], "Failed to detect valid Engulfing"


def test_confluence_failure(mock_df):
    """Test Shape OK but Volume Weak -> Should be False."""
    # Setup Hammer at index 2 w/o Volume
    mock_df.loc[mock_df.index[2], "open"] = 100.0
    mock_df.loc[mock_df.index[2], "close"] = 102.0
    mock_df.loc[mock_df.index[2], "low"] = 94.0
    mock_df.loc[mock_df.index[2], "high"] = 102.0

    # Weak Volume
    mock_df.loc[mock_df.index[2], "volume"] = 1000  # Equal to SMA, not > 1.5x

    analyzer = PatternAnalyzer(mock_df)
    result = analyzer.check_patterns()

    assert not result["bullish_hammer"].iloc[2], "Hammer should fail without volume"
