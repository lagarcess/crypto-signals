"""Unit tests for the pattern analysis module."""

import pandas as pd
import pytest
from crypto_signals.analysis.indicators import TechnicalIndicators
from crypto_signals.analysis.patterns import PatternAnalyzer

# ... (rest of imports or code)
# I need to use separate Replace calls if they are far apart.
# Wait, I can't restart the file content in the middle of a ReplacementChunk if I targeted Lines 1-8?
# I will use MULTI REPL to do both changes in one go.

# Actually, I am using replace_file_content tool. I can only do SINGLE contiguous block.
# So I must do 2 calls or use multi_replace.
# I will use multi_replace_file_content.


@pytest.fixture
def mock_df():
    """Create a mock DataFrame for testing basic patterns."""
    dates = pd.date_range(start="2023-01-01", periods=5, freq="h")
    df = pd.DataFrame(index=dates)

    # Initialize basic columns
    df["open"] = [100.0, 100.0, 100.0, 100.0, 100.0]
    df["high"] = [110.0, 110.0, 110.0, 110.0, 110.0]
    df["low"] = [90.0, 90.0, 90.0, 90.0, 90.0]
    df["close"] = [105.0, 105.0, 105.0, 105.0, 105.0]
    df["volume"] = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]

    # Indicator Columns required for Confluence
    df["EMA_50"] = [120.0] * 5  # Downtrend context
    df["RSI_14"] = [40.0] * 5  # Oversold context
    df["VOL_SMA_20"] = [1000.0] * 5  # Base volume

    # Advanced / Refined columns defaults
    df["ATRr_14"] = 1.0
    df["ATR_14"] = 1.0
    df["ATR_SMA_20"] = 2.0  # VCP Passed (1.0 < 2.0)
    df["volume_expansion"] = True  # Default passes
    df["MFI_14"] = 50.0  # Neutral default

    return df


class TestBasicPatterns:
    """Tests for basic pattern shapes (Hammer, Engulfing)."""

    def test_bullish_hammer_detection(self, mock_df):
        """Test Hammer: Lower Wick >= 2*Body, Upper <= 0.5*Body."""
        # Setup Hammer at index 2
        # Body = 2 (100 to 102)
        # Lower Wick = 6 (94 to 100) -> 3x Body -> OK
        idx = mock_df.index[2]
        mock_df.loc[idx, "open"] = 100.0
        mock_df.loc[idx, "close"] = 102.0
        mock_df.loc[idx, "low"] = 94.0
        mock_df.loc[idx, "high"] = 102.0
        mock_df.loc[idx, "volume"] = 2000
        mock_df["volume_expansion"] = True
        mock_df["EMA_50"] = 90.0  # Force Uptrend for basic shape verification
        analyzer = PatternAnalyzer(mock_df)
        result = analyzer.check_patterns()

        assert (
            bool(result["bullish_hammer"].iloc[2]) is True
        ), "Failed to detect valid Hammer"
        assert (
            bool(result["bullish_hammer"].iloc[0]) is False
        ), "False positive on normal candle"

    def test_bullish_engulfing_detection(self, mock_df):
        """Test Engulfing: Current Green engulfs Previous Red."""
        # Index 3: Red Candle (102 -> 100)
        idx_prev = mock_df.index[3]
        mock_df.loc[idx_prev, "open"] = 102.0
        mock_df.loc[idx_prev, "close"] = 100.0

        # Index 4: Green (100 -> 104), Engulfs 3
        idx_curr = mock_df.index[4]
        mock_df.loc[idx_curr, "open"] = 100.0
        mock_df.loc[idx_curr, "close"] = 104.0
        mock_df.loc[idx_curr, "volume"] = 2000
        mock_df["EMA_50"] = 90.0  # Force Uptrend

        analyzer = PatternAnalyzer(mock_df)
        result = analyzer.check_patterns()

        assert (
            bool(result["bullish_engulfing"].iloc[4]) is True
        ), "Failed to detect valid Engulfing"


class TestAdvancedPatterns:
    """Tests for complex patterns (Morning Star, Piercing Line, Soldiers)."""

    @pytest.fixture
    def base_df(self):
        """Create a larger dataframe for advanced patterns."""
        dates = pd.date_range(start="2024-01-01", periods=100, freq="D")
        df = pd.DataFrame(
            {
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 100.0,
                "volume": 1000.0,
            },
            index=dates,
        )
        # Mock Indicators
        df["EMA_50"] = 90.0
        df["RSI_14"] = 30.0
        df["ATRr_14"] = 2.0
        df["ATR_14"] = 2.0
        df["ATR_SMA_20"] = 3.0
        df["VOL_SMA_20"] = 1000.0
        df["BBL_20_2.0"] = 90.0
        df["MFI_14"] = 15.0
        df["volume_expansion"] = True
        return df

    def update_row(self, df, idx, open_p, high_p, low_p, close_p, vol_p):
        """Helper to update OHLCV row safely."""
        # Handle negative indexing manualy if needed, but pd usually handles iloc
        # Can't mix loc with integer position easily if index is dates
        # Use iloc for setting columns by position for the row
        c_open = df.columns.get_loc("open")
        c_high = df.columns.get_loc("high")
        c_low = df.columns.get_loc("low")
        c_close = df.columns.get_loc("close")
        c_vol = df.columns.get_loc("volume")

        df.iloc[idx, c_open] = open_p
        df.iloc[idx, c_high] = high_p
        df.iloc[idx, c_low] = low_p
        df.iloc[idx, c_close] = close_p
        df.iloc[idx, c_vol] = vol_p

    def test_morning_star_strict(self, base_df):
        """Test Morning Star with strict RSI Divergence requirement."""
        # t-2: Large Red
        self.update_row(base_df, -3, 110, 112, 100, 100, 1000)
        # t-1: Small Star, Gap Down
        self.update_row(base_df, -2, 98, 99, 97, 98, 1000)
        # t: Large Green, Penetrate t-2 (Mid > 105)
        self.update_row(base_df, -1, 99, 106, 98, 106, 2000)

        # Context: Price < EMA 50 (Downtrend)
        base_df["EMA_50"] = 150.0
        TechnicalIndicators.add_all_indicators(base_df)

        # Override Analysis with Divergence mock
        class MockAnalyzerWithDiv(PatternAnalyzer):
            def _detect_bullish_rsi_divergence(self):
                s = pd.Series([False] * len(self.df), index=self.df.index)
                s.iloc[-1] = True
                return s

        base_df["ATRr_14"] = 1.0
        base_df["ATR_SMA_20"] = 2.0  # VCP Pass

        analyzer = MockAnalyzerWithDiv(base_df)
        res = analyzer.check_patterns()

        assert (
            bool(res.iloc[-1]["morning_star"]) is True
        ), "Morning Star with Div should pass"

    def test_three_white_soldiers_volume_step(self, base_df):
        """Test Three White Soldiers with Volume Step requirement."""
        # t-2
        self.update_row(base_df, -3, 100, 103.1, 99, 103, 1000)
        # t-1
        self.update_row(base_df, -2, 101, 104.1, 100, 104, 1500)
        # t
        self.update_row(base_df, -1, 102, 105.1, 101, 105, 2000)

        TechnicalIndicators.add_all_indicators(base_df)
        base_df["EMA_50"] = 90.0  # Uptrend
        base_df["ATRr_14"] = 1.0
        base_df["ATR_SMA_20"] = 2.0
        base_df["volume_expansion"] = True

        analyzer = PatternAnalyzer(base_df)
        res = analyzer.check_patterns()

        assert (
            bool(res.iloc[-1]["three_white_soldiers"]) is True
        ), "Soldiers with Vol Step pass"

        # Fail Case: Decaying Volume
        # base_df.iloc[-1, base_df.columns.get_loc("volume")] = 1400
        self.update_row(base_df, -1, 102, 105.1, 101, 105, 1400)

        analyzer_fail = PatternAnalyzer(base_df)
        res_fail = analyzer_fail.check_patterns()
        assert (
            bool(res_fail.iloc[-1]["three_white_soldiers"]) is False
        ), "Soldiers with Vol Decay fail"

    def test_piercing_line(self, base_df):
        """Test Piercing Line with Bollinger Band check."""
        # t-1: Large Red
        self.update_row(base_df, -2, 110, 110.5, 99.5, 100, 1000)
        # t: Green, Gap Down, Close > Midpoint (105)
        self.update_row(base_df, -1, 98, 106.5, 97, 106, 2000)

        base_df["BBL_20_2.0"] = 98.0
        base_df["ATRr_14"] = 1.0
        base_df["ATR_SMA_20"] = 2.0

        analyzer = PatternAnalyzer(base_df)
        res = analyzer.check_patterns()

        assert bool(res.iloc[-1]["piercing_line"]) is True


class TestMacroPatterns:
    """Tests for multi-candle macro shapes (Bull Flag, etc)."""

    @pytest.fixture
    def base_df(self):
        dates = pd.date_range(start="2024-01-01", periods=150, freq="D")
        df = pd.DataFrame(
            {
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000.0,
            },
            index=dates,
        )
        return df

    def test_bull_flag_strict(self, base_df):
        """
        Bull Flag:
        1. Pole > 15% (t-5 to t-10)
        2. Retracement < 50%
        3. Volume Decay in Consolidation
        """
        # Base level
        base_df["close"] = 100.0
        base_df["volume"] = 2000.0

        # Pole Start (-10)
        base_df.iloc[-10:, base_df.columns.get_loc("close")] = 100.0
        # Pole Rise (-5) -> 120 (+20%)
        base_df.iloc[-5:, base_df.columns.get_loc("close")] = 120.0  # To 120
        base_df.iloc[-5, base_df.columns.get_loc("high")] = 122.0  # Top
        base_df.iloc[-5, base_df.columns.get_loc("low")] = (
            115.0  # Low of Pole Top candle must be high enough to not trigger retracement
        )
        base_df.iloc[-5, base_df.columns.get_loc("volume")] = 5000.0  # Pole Vol
        # Consolidation (t-4 to t)
        for i in range(-4, 0):
            base_df.iloc[i, base_df.columns.get_loc("high")] = 118.0
            base_df.iloc[i, base_df.columns.get_loc("low")] = 114.0  # > 110
            base_df.iloc[i, base_df.columns.get_loc("close")] = 116.0
            # Volume Decay
            base_df.iloc[i, base_df.columns.get_loc("volume")] = 1000.0 - (
                100 * (4 + i)
            )

        # Breakout at t
        base_df.iloc[-1, base_df.columns.get_loc("close")] = 112.0
        base_df.iloc[-1, base_df.columns.get_loc("low")] = (
            112.0  # > Pole Low, ensures <50% retracement (122-112=10, 10/22 < 0.5)
        )
        base_df.iloc[-1, base_df.columns.get_loc("volume")] = 5000.0  # Breakout Vol
        TechnicalIndicators.add_all_indicators(base_df)
        base_df["EMA_50"] = 90.0
        base_df["ATRr_14"] = 1.0
        base_df["ATR_SMA_20"] = 2.0
        base_df["volume_expansion"] = True

        analyzer = PatternAnalyzer(base_df)
        res = analyzer.check_patterns()

        analyzer = PatternAnalyzer(base_df)
        res = analyzer.check_patterns()

        # Debugging / Granular Assertions
        # 1. Pole Check (manually verify)
        # ret_5d = base_df["close"].pct_change(5)
        # pole = ret_5d.shift(3).rolling(8).max()
        # assert pole.iloc[-1] > 0.15, f"Pole strength failed: {pole.iloc[-1]}"

        # 2. Retracement Check
        # High=122, Low=112 (Breakout), Pole Low=100.
        # Height=22. Drop=10. Ratio=0.45.

        # 3. Volume Decay
        # SMA5 at t-1 vs SMA5 at t-4
        vol_sma_5 = base_df["volume"].rolling(5).mean()
        v_t1 = vol_sma_5.iloc[-2]  # t-1
        v_t4 = vol_sma_5.iloc[-5]  # t-4
        assert v_t1 < v_t4, f"Volume Decay failed: {v_t1} >= {v_t4}"

        assert (
            bool(res.iloc[-1]["bull_flag"]) is True
        ), f"Strict Bull Flag Check. Pole: {analyzer._detect_bull_flag().iloc[-1]}"


class TestInvertedHammer:
    def test_inverted_hammer_confirmation(self, mock_df):
        # t-1: Inverted Hammer (Index 3)
        mock_df["low"] = [100.0, 98.0, 96.0, 94.0, 92.0]  # Downtrend, explicit floats
        mock_df["volume"] = [2000.0] * 5  # High volume
        mock_df["EMA_50"] = 90.0  # Price (93) > 90. Uptrend context satisfied.
        mock_df["MFI_14"] = 10.0  # Oversold
        mock_df["VOL_SMA_20"] = 100.0  # Volume (2000) > 100. Expansion True.

        # Set row 3 (t-1)
        idx_prev = mock_df.index[3]
        mock_df.loc[idx_prev, "open"] = 93.0
        mock_df.loc[idx_prev, "close"] = 93.5
        mock_df.loc[idx_prev, "high"] = 95.0
        mock_df.loc[idx_prev, "low"] = 92.9

        # Set row 4 (t) -> Confirmation
        # t close > t-1 body top (93.5)
        idx_curr = mock_df.index[4]
        mock_df.loc[idx_curr, "open"] = 93.0
        mock_df.loc[idx_curr, "close"] = 96.0
        # Volume expansion calculated by check_patterns requires VOL_SMA_20
        # Logic: volume > 1.5 * VOL_SMA_20 (or factor). 2000 > 1.5*100. True.

        analyzer = PatternAnalyzer(mock_df)
        result = analyzer.check_patterns()

        assert (
            bool(result["inverted_hammer"].iloc[-1]) is True
        ), "Inverted Hammer confirmed"
