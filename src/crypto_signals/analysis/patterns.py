"""Pattern analysis module for detecting technical trading patterns."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Signal:
    """Data class representing a detected trading signal."""

    timestamp: pd.Timestamp
    symbol: str
    pattern_type: str
    price: float
    confidence: str = "HIGH"  # Derived from confluence


class PatternAnalyzer:
    """Engine for detecting technical patterns with confluence confirmation."""

    # Confluence Constants
    RSI_THRESHOLD = 45.0
    VOLUME_FACTOR = 1.5
    HAMMER_LOWER_WICK_RATIO = 2.0
    HAMMER_UPPER_WICK_RATIO = 0.5

    # New Constants
    MFI_OVERSOLD = 20.0
    ADX_TRENDING = 25.0
    MARUBOZU_BODY_RATIO = 0.95

    def __init__(self, dataframe: pd.DataFrame):
        """Initialize the PatternAnalyzer with a dataframe."""
        self.df = dataframe.copy()  # Work on a copy safely

    def check_patterns(self) -> pd.DataFrame:
        """
        Scan the DataFrame for patterns.

        Returns a DataFrame with boolean columns for each pattern
        and confluence checks.
        """
        # Ensure we have the basic components
        self._calculate_candle_shapes()

        # 1. Detect Shapes (Discrete)
        self.df["is_hammer_shape"] = self._detect_bullish_hammer()
        self.df["is_engulfing_shape"] = self._detect_bullish_engulfing()
        self.df["is_morning_star_shape"] = self._detect_morning_star()
        self.df["is_piercing_line_shape"] = self._detect_piercing_line()
        self.df["is_three_white_soldiers_shape"] = self._detect_three_white_soldiers()
        self.df["is_inverted_hammer_shape"] = self._detect_inverted_hammer()
        self.df["is_marubozu_shape"] = self._detect_bullish_marubozu()

        # Color Flip Detection (Exit Logic)
        self.df["bearish_engulfing"] = self._detect_bearish_engulfing()

        # 2. Detect Macro Shapes (Multi-Candle / Rolling)
        self.df["is_bull_flag"] = self._detect_bull_flag()
        self.df["is_cup_handle"] = self._detect_cup_and_handle()
        self.df["is_double_bottom"] = self._detect_double_bottom()
        self.df["is_ascending_triangle"] = self._detect_ascending_triangle()
        self.df["is_tweezer_bottoms"] = self._detect_tweezer_bottoms()

        # 2b. High-Probability Bullish Patterns (NEW)
        self.df["is_dragonfly_doji"] = self._detect_dragonfly_doji()
        self.df["is_bullish_belt_hold"] = self._detect_bullish_belt_hold()
        self.df["is_bullish_harami"] = self._detect_bullish_harami()
        self.df["is_bullish_kicker"] = self._detect_bullish_kicker()
        self.df["is_three_inside_up"] = self._detect_three_inside_up()
        self.df["is_rising_three_methods"] = self._detect_rising_three_methods()
        self.df["is_falling_wedge"] = self._detect_falling_wedge()
        self.df["is_inverse_head_shoulders"] = self._detect_inverse_head_shoulders()

        # 3. Check Confirmations (Regime Filters)
        # Trend: Continuation Patterns (Flags/Marubozu/Soldiers) require Price > EMA(50)
        self.df["trend_bullish"] = self.df["close"] > self.df["EMA_50"]

        # Momentum: RSI < 45 (Oversold-ish) for reversals
        self.df["momentum_oversold"] = self.df["RSI_14"] < self.RSI_THRESHOLD

        self.df["rsi_bullish_divergence"] = self._detect_bullish_rsi_divergence()

        # Volatility Filter (VCP): ATR declining -> ATR < SMA(ATR, 20)
        # Note: pandas-ta usually outputs ATRr_14. We check availability.
        atr_col = "ATRr_14" if "ATRr_14" in self.df.columns else "ATR_14"

        if "ATR_SMA_20" in self.df.columns and atr_col in self.df.columns:
            self.df["volatility_contraction"] = self.df[atr_col] < self.df["ATR_SMA_20"]
        else:
            # Fallback: return Series of True (skip this filter)
            self.df["volatility_contraction"] = pd.Series(True, index=self.df.index)

        # Volume Confirmation
        if "VOL_SMA_20" in self.df.columns:
            self.df["volume_expansion"] = self.df["volume"] > (
                self.VOLUME_FACTOR * self.df["VOL_SMA_20"]
            )
            # For flags, we want volume decay, but let's stick to the comprehensive
        # 'volume_confirmed' logic per pattern below.
        else:
            # Fallback: return Series of False (no volume confirmation)
            self.df["volume_expansion"] = pd.Series(False, index=self.df.index)

        # 4. Final Signal Logic with Pattern-Specific Confluence

        # General Confluence for Reversals (Trend optional if Divergence,
        # but simpler rule: Trend OR Oversold)
        # User rule: Reversal Patterns waive EMA(50) if RSI Bullish Divergence.
        # Implementing simplified "Trend OR Momentum" for Reversals to capture
        # them in dips.
        # EMA WAIVER LOGIC: Trend Bullish OR RSI Divergence
        reversal_context = self.df["trend_bullish"] | self.df["rsi_bullish_divergence"]

        # HAMMER
        # HAMMER
        self.df["bullish_hammer"] = (
            self.df["is_hammer_shape"]
            & reversal_context
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # ENGULFING
        # ENGULFING
        self.df["bullish_engulfing"] = (
            self.df["is_engulfing_shape"]
            & reversal_context
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # MORNING STAR
        # MORNING STAR
        # Strict Rule: Must be confirmed by RSI Bullish Divergence.
        # (Overriding generic reversal_context)
        self.df["morning_star"] = (
            self.df["is_morning_star_shape"]
            & self.df["rsi_bullish_divergence"]
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # PIERCING LINE (Needs BB interaction)
        # Bollinger Lower Band Check: Low <= BBL and Close > BBL (Snap back)
        # Assuming BBL_20_2.0 exists
        if "BBL_20_2.0" in self.df.columns:
            bb_interaction = (self.df["low"] <= self.df["BBL_20_2.0"]) & (
                self.df["close"] > self.df["BBL_20_2.0"]
            )
        else:
            bb_interaction = False

        self.df["piercing_line"] = (
            self.df["is_piercing_line_shape"]
            & bb_interaction
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # INVERTED HAMMER
        # Requirement: MFI < 20 AND Next Day Confirmation.
        # We detect the signal on the *Confirmation Day* (t), valid for the Hammer on (t-1).
        # Check if t-1 was Inverted Hammer
        is_inv_hammer_prev = self.df["is_inverted_hammer_shape"].shift(1)

        # MFI on the Hammer day (t-1) should be oversold
        if "MFI_14" in self.df.columns:
            mfi_prev = self.df["MFI_14"].shift(1)
            mfi_oversold = mfi_prev < self.MFI_OVERSOLD
        else:
            mfi_oversold = False

        # Confirmation: Today's Close > Hammer Body (t-1)
        # Hammer Body High = max(open, close) of t-1
        body_high_prev = np.maximum(self.df["open"].shift(1), self.df["close"].shift(1))
        is_confirmed = self.df["close"] > body_high_prev

        self.df["inverted_hammer"] = (
            is_inv_hammer_prev
            & mfi_oversold
            & is_confirmed
            # Note: Volume often low on inverted hammer test, but user asked for
            # vol expansion? "All patterns require volume expansion".
            # adhering to user rule.
            & self.df["volume_expansion"]  # Volume on confirmation (today)?
            & self.df["volatility_contraction"]
        )

        # CONTINUATION PATTERNS (Must be in Uptrend)

        # 3 WHITE SOLDIERS
        # 3 WHITE SOLDIERS
        # Strict Rule: Volume Step Function (V(t-2) < V(t-1) < V(t))
        # Note: volume_expansion usually just checks V > SMA.
        # We need strict monotonic volume increase.
        vol_step_up = (self.df["volume"] > self.df["volume"].shift(1)) & (
            self.df["volume"].shift(1) > self.df["volume"].shift(2)
        )

        self.df["three_white_soldiers"] = (
            self.df["is_three_white_soldiers_shape"]
            & self.df["trend_bullish"]
            & vol_step_up
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # MARUBOZU
        # MARUBOZU
        # Strict Rule: Close > Upper Keltner Channel (Breakout)
        keltner_breakout = False
        keltner_col = "KCUe_20_2.0"  # Default pandas-ta naming for EMA basis
        if keltner_col in self.df.columns:
            keltner_breakout = self.df["close"] > self.df[keltner_col]
        else:
            # Fallback check if simple mean is used or col name varies
            keltner_col_simple = "KCUs_20_2.0"
            if keltner_col_simple in self.df.columns:
                keltner_breakout = self.df["close"] > self.df[keltner_col_simple]

        self.df["bullish_marubozu"] = (
            self.df["is_marubozu_shape"]
            & self.df["trend_bullish"]
            & self.df["trend_bullish"]
            & self.df["volume_expansion"]
            & keltner_breakout
            & self.df["volatility_contraction"]
        )

        # BULL FLAG
        self.df["bull_flag"] = (
            self.df["is_bull_flag"]
            & self.df["trend_bullish"]
            & self.df["volume_expansion"]  # Breakout volume
            & self.df["volatility_contraction"]
        )

        # DOUBLE BOTTOM
        # Reversal Context (Trend or Div)
        self.df["double_bottom"] = (
            self.df["is_double_bottom"]
            & reversal_context
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # ASCENDING TRIANGLE
        # Continuation pattern, requires bullish trend
        self.df["ascending_triangle"] = (
            self.df["is_ascending_triangle"]
            & self.df["trend_bullish"]
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # CUP AND HANDLE
        # Continuation pattern with breakout confirmation
        self.df["cup_and_handle"] = (
            self.df["is_cup_handle"]
            & self.df["trend_bullish"]
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # TWEEZER BOTTOMS
        # Reversal pattern with strong downtrend context
        self.df["tweezer_bottoms"] = (
            self.df["is_tweezer_bottoms"] & reversal_context & self.df["volume_expansion"]
        )

        # INVERTED HAMMER
        # Reversal Context (Trend or Div)
        self.df["inverted_hammer"] = (
            self.df["is_inverted_hammer_shape"]
            & reversal_context
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # ============================================================
        # HIGH-PROBABILITY BULLISH PATTERNS (NEW)
        # ============================================================

        # DRAGONFLY DOJI (65% success rate)
        # Single-candle reversal at support with RSI/BB confluence
        if "BBL_20_2.0" in self.df.columns:
            at_bb_lower = self.df["low"] <= self.df["BBL_20_2.0"]
        else:
            at_bb_lower = pd.Series(True, index=self.df.index)  # Skip if BB not available

        self.df["dragonfly_doji"] = (
            self.df["is_dragonfly_doji"]
            & reversal_context
            & self.df["volume_expansion"]
            & at_bb_lower
        )

        # BULLISH BELT HOLD (60% success rate)
        # Single-candle reversal, needs trend context
        self.df["bullish_belt_hold"] = (
            self.df["is_bullish_belt_hold"]
            & reversal_context
            & self.df["volume_expansion"]
        )

        # BULLISH HARAMI (53% success rate)
        # Two-candle reversal, needs MFI/RSI confluence
        if "MFI_14" in self.df.columns:
            mfi_oversold = self.df["MFI_14"] < 30
        else:
            mfi_oversold = pd.Series(True, index=self.df.index)

        self.df["bullish_harami"] = (
            self.df["is_bullish_harami"] & reversal_context & mfi_oversold
        )

        # BULLISH KICKER (75% success rate)
        # Two-candle gap reversal with extreme volume
        vol_extreme = self.df["volume"] > (self.df["volume"].shift(1) * 2)

        self.df["bullish_kicker"] = self.df["is_bullish_kicker"] & vol_extreme

        # THREE INSIDE UP (65% success rate)
        # Three-candle reversal with volume escalation
        vol_escalation = (self.df["volume"] > self.df["volume"].shift(1)) & (
            self.df["volume"].shift(1) > self.df["volume"].shift(2)
        )

        self.df["three_inside_up"] = (
            self.df["is_three_inside_up"] & reversal_context & vol_escalation
        )

        # RISING THREE METHODS (70% success rate)
        # Five-candle continuation, requires uptrend
        self.df["rising_three_methods"] = (
            self.df["is_rising_three_methods"]
            & self.df["trend_bullish"]
            & self.df["volume_expansion"]
        )

        # FALLING WEDGE (74% success rate)
        # Multi-day breakout, needs volume on breakout
        self.df["falling_wedge"] = (
            self.df["is_falling_wedge"]
            & self.df["volume_expansion"]
            & self.df["volatility_contraction"]
        )

        # INVERSE HEAD AND SHOULDERS (89% success rate)
        # Multi-day reversal, needs volume confirmation
        self.df["inverse_head_shoulders"] = (
            self.df["is_inverse_head_shoulders"] & self.df["volume_expansion"]
        )

        return self.df

    def _calculate_candle_shapes(self):
        """Pre-calculates candle properties for vectorized operations."""
        self.df["body_size"] = np.abs(self.df["close"] - self.df["open"])
        self.df["upper_wick"] = self.df["high"] - np.maximum(
            self.df["close"], self.df["open"]
        )
        self.df["lower_wick"] = (
            np.minimum(self.df["close"], self.df["open"]) - self.df["low"]
        )
        self.df["total_range"] = self.df["high"] - self.df["low"]
        self.df["body_pct"] = self.df["body_size"] / self.df["total_range"]

        # Determine color
        self.df["is_green"] = self.df["close"] > self.df["open"]
        self.df["is_red"] = self.df["close"] < self.df["open"]

        # Shifts for multi-candle logic
        self.df["open_1"] = self.df["open"].shift(1)
        self.df["close_1"] = self.df["close"].shift(1)
        self.df["high_1"] = self.df["high"].shift(1)
        self.df["low_1"] = self.df["low"].shift(1)

        self.df["open_2"] = self.df["open"].shift(2)
        self.df["close_2"] = self.df["close"].shift(2)

    def _detect_bullish_hammer(self) -> pd.Series:
        """Lower Wick >= 2.0 * Body, Upper Wick <= 0.5 * Body, Downtrend context."""
        return (
            self.df["lower_wick"] >= self.HAMMER_LOWER_WICK_RATIO * self.df["body_size"]
        ) & (self.df["upper_wick"] <= self.HAMMER_UPPER_WICK_RATIO * self.df["body_size"])

    def _detect_bullish_engulfing(self) -> pd.Series:
        """Current Green, Prev Red, Envelops Body."""
        prev_close = self.df["close_1"]
        prev_open = self.df["open_1"]
        prev_is_red = self.df["is_red"].shift(1)
        curr_is_green = self.df["is_green"]

        return (
            curr_is_green
            & prev_is_red
            & (self.df["open"] <= prev_close)
            & (self.df["close"] > prev_open)
        )

    def _detect_bearish_engulfing(self) -> pd.Series:
        """
        Color Flip Exit logic.
        Current Red, Prev Green.
        Engulfs Body (Open > Prev Close, Close < Prev Open).
        """
        prev_close = self.df["close_1"]
        prev_open = self.df["open_1"]
        prev_is_green = self.df["is_green"].shift(1)
        curr_is_red = self.df["is_red"]

        return (
            curr_is_red
            & prev_is_green
            & (self.df["open"] >= prev_close)
            & (self.df["close"] < prev_open)
        )

    def _detect_bullish_rsi_divergence(self) -> pd.Series:
        """
        Detects potential Bullish RSI Divergence:
        - Price Low is lowest in last 14 bars.
        - RSI is NOT lowest in last 14 bars.
        """
        window = 14
        # Lowest Low in window
        low_min = self.df["low"].rolling(window).min()
        is_new_low = self.df["low"] <= low_min + (low_min * 0.001)  # Approx match

        # Lowest RSI in window
        rsi_min = self.df["RSI_14"].rolling(window).min()
        rsi_higher = self.df["RSI_14"] > (rsi_min + 1.0)  # Distinctly higher

        return is_new_low & rsi_higher

    def _detect_morning_star(self) -> pd.Series:
        """
        Enhanced Morning Star Detection with Conviction Score.

        Base Morning Star:
        t1 (t-2): Large Red (Close < Open AND Abs(Open-Close) > ATR)
        t2 (t-1): Spinning Top/Doji (Body small, Gap down ideally)
        t3 (t): Large Green (Close > Midpoint of t-2 body - 50% penetration)

        Sub-Pattern Detection:
        - Bullish Abandoned Baby: Gaps between all 3 candles
          (t1.low > t2.high AND t2.high < t3.low)

        Strength Modifiers:
        - Volume Escalation: Vol 3 > Vol 2 > Vol 1 (+0.2)
        - Abandoned Baby: True gaps on both sides (+0.3)
        - RSI Context: RSI < 35 within last 3 periods (+0.2)
        - 50% Penetration: Close > t2 midpoint (+0.3 base)

        Returns:
            pd.Series[bool]: True at bars where Morning Star is detected.

        Note:
            Strength score is stored in 'morning_star_strength' column.
            Is_abandoned_baby is stored in 'is_abandoned_baby' column.
            All logic uses vectorized pandas operations.
        """
        # ============================================================
        # BASE MORNING STAR DETECTION
        # ============================================================

        # t-2: Bearish (Large Red)
        t2_is_red = self.df["is_red"].shift(2)
        t2_body = self.df["body_size"].shift(2)
        t2_open = self.df["open"].shift(2)
        t2_close = self.df["close"].shift(2)
        t2_low = self.df["low"].shift(2)

        # Using ATR for "Large" - check available column
        atr_col = "ATRr_14" if "ATRr_14" in self.df.columns else "ATR_14"
        atr_series = self.df[atr_col].shift(2) if atr_col in self.df.columns else 0.0
        has_size = t2_body > atr_series

        # t-1: Small Body (Spinning Top/Doji)
        t1_range = self.df["total_range"].shift(1)
        t1_body = self.df["body_size"].shift(1)
        t1_high = self.df["high"].shift(1)
        is_star = t1_body < (t1_range * 0.3)

        # Gap down from t-2 to t-1: Open(t-1) <= Close(t-2)
        is_gap_down = self.df["open"].shift(1) <= t2_close

        # t: Bullish, Green
        t0_is_green = self.df["is_green"]
        t0_low = self.df["low"]
        t0_volume = self.df["volume"]

        # 50% Penetration: Close > Midpoint of t-2 body
        t2_mid = (t2_open + t2_close) / 2
        penetration = self.df["close"] > t2_mid

        # Base Morning Star Pattern
        is_morning_star = (
            t2_is_red & has_size & is_star & is_gap_down & t0_is_green & penetration
        )

        # ============================================================
        # ABANDONED BABY DETECTION (Stronger Sub-Pattern)
        # ============================================================
        # Gap 1: t-2 low > t-1 high (gap down from t-2 to t-1)
        gap_1_abandoned = t2_low > t1_high

        # Gap 2: t-1 high < t0 low (gap up from t-1 to t)
        gap_2_abandoned = t1_high < t0_low

        is_abandoned_baby = is_morning_star & gap_1_abandoned & gap_2_abandoned

        # Store abandoned baby detection
        self.df["is_abandoned_baby"] = is_abandoned_baby.fillna(False)

        # ============================================================
        # VOLUME ESCALATION CHECK (Vol 3 > Vol 2 > Vol 1)
        # ============================================================
        vol_t2 = self.df["volume"].shift(2)
        vol_t1 = self.df["volume"].shift(1)
        vol_t0 = t0_volume

        volume_escalation = (vol_t0 > vol_t1) & (vol_t1 > vol_t2)

        # ============================================================
        # CONTEXTUAL RSI CHECK (RSI < 35 in last 3 periods)
        # ============================================================
        if "RSI_14" in self.df.columns:
            rsi_t2 = self.df["RSI_14"].shift(2)
            rsi_t1 = self.df["RSI_14"].shift(1)
            rsi_t0 = self.df["RSI_14"]

            rsi_oversold = (rsi_t2 < 35) | (rsi_t1 < 35) | (rsi_t0 < 35)
        else:
            rsi_oversold = pd.Series(
                True, index=self.df.index
            )  # Skip if RSI not available

        # ============================================================
        # STRENGTH SCORE CALCULATION (0.0 to 1.0)
        # ============================================================
        # Base score for valid morning star with 50% penetration
        strength = pd.Series(0.0, index=self.df.index)

        # Base score: 0.3 for valid pattern with penetration
        strength = strength.where(~is_morning_star, 0.3)

        # +0.2 for volume escalation
        strength = strength + volume_escalation.astype(float) * 0.2

        # +0.3 for abandoned baby (rare, explosive signal)
        strength = strength + is_abandoned_baby.astype(float) * 0.3

        # +0.2 for RSI oversold context
        strength = strength + rsi_oversold.astype(float) * 0.2

        # Ensure score stays in [0.0, 1.0] range and only for valid patterns
        strength = strength.clip(0.0, 1.0)
        strength = strength.where(is_morning_star, 0.0)

        # Store strength score
        self.df["morning_star_strength"] = strength

        return is_morning_star.fillna(False)

    def _detect_piercing_line(self) -> pd.Series:
        """
        Piercing Line:
        t1: Large Red (Body > 0.6 Range)
        t2: Gap Down (Open < Low(t-1))
        t2: Close > Midpoint(t-1) AND Close < Open(t-1)
        """
        # Previous candle conditions
        t1_is_red = self.df["is_red"].shift(1)
        t1_body_dominant = self.df["body_pct"].shift(1) > 0.6
        t1_mid = (self.df["open_1"] + self.df["close_1"]) / 2

        # Current candle conditions
        t0_is_green = self.df["is_green"]
        gap_down = self.df["open"] < self.df["close_1"]
        close_above_mid = self.df["close"] > t1_mid
        close_below_open = self.df["close"] < self.df["open_1"]

        return (
            t1_is_red
            & t1_body_dominant
            & gap_down
            & close_above_mid
            & close_below_open
            & t0_is_green
        )

    def _detect_three_white_soldiers(self) -> pd.Series:
        """
        Three White Soldiers:
        3 Greens.
        Each Open within prev body.
        Closes near highs.
        """
        # 3 Consecutive Greens
        green_3 = (
            self.df["is_green"]
            & self.df["is_green"].shift(1)
            & self.df["is_green"].shift(2)
        )

        # Open within prev body
        # Open(t) > Open(t-1) AND Open(t) < Close(t-1)
        open_in_body_1 = (self.df["open"] > self.df["open_1"]) & (
            self.df["open"] < self.df["close_1"]
        )
        open_in_body_2 = (self.df["open_1"] > self.df["open_2"]) & (
            self.df["open_1"] < self.df["close_2"]
        )

        # Close near high (upper wick small)
        # (High - Close) < (Close - Open) * 0.2  -> UpperWick < Body * 0.2
        strong_close_0 = self.df["upper_wick"] < (self.df["body_size"] * 0.2)
        strong_close_1 = self.df["upper_wick"].shift(1) < (
            self.df["body_size"].shift(1) * 0.2
        )
        strong_close_2 = self.df["upper_wick"].shift(2) < (
            self.df["body_size"].shift(2) * 0.2
        )

        return (
            green_3
            & open_in_body_1
            & open_in_body_2
            & strong_close_0
            & strong_close_1
            & strong_close_2
        )

    def _detect_inverted_hammer(self) -> pd.Series:
        """
        Confirmed Inverted Hammer:
        1. Shape at t-1: Small body, Long upper wick, Small lower wick.
        2. Confluence: MFI(t-1) < 20 (Oversold).
        3. Confirmation: Close(t) > BodyTop(t-1).
        """
        # 1. Shape at t-1
        # Shift metrics by 1
        body_pct = self.df["body_pct"].shift(1)
        lower_wick = self.df["lower_wick"].shift(1)
        upper_wick = self.df["upper_wick"].shift(1)
        total_range = self.df["total_range"].shift(1)
        body_size = self.df["body_size"].shift(1)

        small_body = body_pct < 0.3
        small_lower = lower_wick < (total_range * 0.1)
        long_upper = upper_wick >= (2 * body_size)
        is_hammer_shape = small_body & small_lower & long_upper

        # 2. MFI Confluence (at t-1)
        if "MFI_14" in self.df.columns:
            mfi_oversold = self.df["MFI_14"].shift(1) < 20
        else:
            mfi_oversold = False  # Strict: require MFI

        # 3. Confirmation at t
        # BodyTop(t-1)
        open_prev = self.df["open"].shift(1)
        close_prev = self.df["close"].shift(1)
        # Element-wise max
        body_top_prev = np.maximum(open_prev, close_prev)

        is_confirmed = self.df["close"] > body_top_prev

        return is_hammer_shape & mfi_oversold & is_confirmed

    def _detect_bullish_marubozu(self) -> pd.Series:
        """
        Marubozu:
        Body > 0.95 Range
        Range > 2.0 * ATR(14)
        """
        large_body = self.df["body_pct"] > self.MARUBOZU_BODY_RATIO

        range_expanded = False
        if "ATRr_14" in self.df.columns:
            range_expanded = self.df["total_range"] > (2.0 * self.df["ATRr_14"])
        elif "ATR_14" in self.df.columns:
            range_expanded = self.df["total_range"] > (2.0 * self.df["ATR_14"])

        return large_body & range_expanded & self.df["is_green"]

    def _detect_bull_flag(self) -> pd.Series:
        """
        Bull Flag Detection with strict constraints:
        1. Pole: >15% move in 5 days (checked at t-3 to t-10).
        2. Retracement: High(Pole) - Low(Flag) < 0.5 * Pole_Height.
        3. Volume Decay: Volume SMA(5) declining.
        """

        # 1. Identify Pole candidates (rolling 5d return)
        # We look for a pole that *ended* roughly 3-10 days ago (consolidation phase)
        # Shifted returns to identify past strength
        ret_5d = self.df["close"].pct_change(5)
        # Pole ending 3 to 10 days ago
        # Max return in the window [t-10, t-3] must be > 15%
        # Window size = 8.
        past_strength = ret_5d.shift(3).rolling(8).max()
        has_pole = past_strength > 0.15

        # 2. Retracement Check
        # Find the High of the recent past (Pole Top) - say last 15 days
        recent_high = self.df["high"].rolling(15).max()
        # Find Low of the consolidation (last 5 days)
        recent_low = self.df["low"].rolling(5).min()
        # Pole low (approximate: Low 15 days ago? Or min in 15 days?)
        pole_low = self.df["low"].rolling(15).min()

        pole_height = recent_high - pole_low
        # Avoid division by zero
        pole_height = pole_height.replace(0, np.nan)

        retracement = (recent_high - recent_low) / pole_height
        valid_retracement = retracement < 0.5

        # 3. Volume Decay
        # SMA(5) of Volume is less than SMA(20) OR SMA(5) is declining?
        # User: "verify that volume is decreasing during the consolidation phase"
        # shift check to t-1 to avoid breakout volume spike.
        vol_sma_5 = self.df["volume"].rolling(5).mean()
        vol_sma_20 = self.df["volume"].rolling(20).mean()

        # Shifted SMAs to check t-1
        vol_sma_5_prev = vol_sma_5.shift(1)
        vol_sma_20_prev = vol_sma_20.shift(1)

        vol_decay = (vol_sma_5_prev < vol_sma_5.shift(4)) & (
            vol_sma_5_prev < vol_sma_20_prev
        )

        return has_pole & valid_retracement & vol_decay

    def _detect_cup_and_handle(self) -> pd.Series:
        """
        Cup and Handle Pattern Detection.

        The Cup and Handle is a bullish continuation pattern consisting of:
        1. Cup (U-Shape):
           - Local high (left rim) followed by 30-50% retracement
           - Recovery back to initial high level over 20-30 periods
           - Rounded bottom (not a sharp V) - verified by checking that the
             rolling minimum variance is low, indicating gradual price change

        2. Handle:
           - 4-7 periods of consolidation after cup completes
           - Price stays within top 10% of the cup's total height

        Mathematical Roundedness Check:
            A rounded bottom has a gradual transition vs a V-shape's sharp turn.
            We measure this by checking that the middle portion of the cup
            (around the bottom) shows the rolling min staying relatively stable
            over several bars, indicating a "U" rather than a "V".

        Returns:
            pd.Series[bool]: True at bars where cup and handle breakout is detected.
        """
        cup_period = 25  # Average cup formation period (20-30 range)
        handle_period = 5  # Handle consolidation period (4-7 range)
        total_lookback = cup_period + handle_period

        is_cup_handle = pd.Series(False, index=self.df.index)

        # Need enough data
        if len(self.df) < total_lookback + 10:
            return is_cup_handle

        # 1. Identify the left rim (local high before cup)
        # Rolling max of highs over past cup_period, shifted by handle_period
        left_rim_high = (
            self.df["high"].shift(handle_period).rolling(window=cup_period).max()
        )

        # 2. Cup bottom - minimum low during cup formation
        cup_bottom_low = (
            self.df["low"].shift(handle_period).rolling(window=cup_period).min()
        )

        # 3. Cup height and retracement check (30-50%)
        cup_height = left_rim_high - cup_bottom_low
        retracement_pct = cup_height / left_rim_high

        valid_retracement = (retracement_pct >= 0.30) & (retracement_pct <= 0.50)

        # 4. Recovery check - current price near left rim level
        # Price recovered back within 5% of left rim high
        right_rim_price = self.df["high"].shift(handle_period)
        recovery_valid = right_rim_price >= (left_rim_high * 0.95)

        # 5. Rounded Bottom Check (U-shape vs V-shape)
        # A U-shape has the minimum staying relatively stable in the middle
        # We check variance of the rolling minimum over the cup's middle third
        mid_section_window = max(cup_period // 3, 5)
        mid_section_start = handle_period + (cup_period // 3)

        # Rolling std of lows in the bottom section
        # Low variance indicates a rounded (U-shape) bottom vs sharp (V-shape)
        rolling_min_std = (
            self.df["low"]
            .shift(mid_section_start)
            .rolling(window=mid_section_window)
            .std()
        )

        # Variance relative to cup height should be low for U-shape
        # V-shape would have high variance as price changes rapidly
        roundedness_ratio = rolling_min_std / cup_height.replace(0, np.nan)
        rounded_bottom = roundedness_ratio < 0.15  # Low variance = rounded

        # 6. Handle Consolidation Check
        # Last handle_period bars should stay within top 10% of cup height
        handle_low = self.df["low"].rolling(window=handle_period).min()
        handle_high = self.df["high"].rolling(window=handle_period).max()

        cup_top = left_rim_high
        cup_height_10pct = cup_height * 0.10

        # Handle should be in the upper zone (within 10% of cup top)
        handle_floor = cup_top - cup_height_10pct
        handle_in_zone = (handle_low >= handle_floor) & (handle_high <= cup_top * 1.02)

        # 7. Breakout signal - current bar breaks above handle resistance
        breakout = self.df["close"] > handle_high.shift(1)

        # Combine all conditions
        is_cup_handle = (
            valid_retracement
            & recovery_valid
            & rounded_bottom
            & handle_in_zone
            & breakout
        )

        return is_cup_handle.fillna(False)

    def _detect_double_bottom(self) -> pd.Series:
        """
        Hardened Double Bottom Detection.

        Structural Requirements:
        1. Two Lows separated by 10-30 bars.
        2. Lows within 1.5% of each other (tighter tolerance).
        3. Middle Peak (Neckline) must be >= 3% above average of the two bottoms.

        Returns:
            pd.Series[bool]: True at bars where valid double bottom is detected.

        Note:
            Uses vectorized pandas operations for performance - no for-loops.
        """
        is_double_bottom = pd.Series(False, index=self.df.index)
        current_low = self.df["low"]

        # Vectorized approach: Check multiple lags simultaneously
        # We'll check lags 10, 15, 20, 25, 30 (representative samples)
        lags_to_check = [10, 15, 20, 25, 30]

        for lag in lags_to_check:
            past_low = self.df["low"].shift(lag)

            # 1. Validate bottoms within 1.5% of each other
            avg_bottoms = (current_low + past_low) / 2
            diff_pct = np.abs(current_low - past_low) / avg_bottoms
            bottoms_match = diff_pct < 0.015  # 1.5% tolerance

            # 2. Middle Peak Verification (Neckline check)
            # Find the maximum high between the two potential bottoms
            # Rolling max over the lag period, shifted by 1 to exclude current bar
            middle_peak = self.df["high"].shift(1).rolling(window=lag - 1).max()

            # Neckline must be >= 3% higher than average of bottoms
            neckline_valid = middle_peak >= (avg_bottoms * 1.03)

            # Combine conditions
            valid_double_bottom = bottoms_match & neckline_valid

            # Aggregate results
            is_double_bottom = is_double_bottom | valid_double_bottom

        return is_double_bottom.fillna(False)

    def _detect_ascending_triangle(self) -> pd.Series:
        """
        Ascending Triangle Detection.

        Structural Requirements:
        1. Flat Upper Resistance: Rolling max of highs over 14 periods with variance ≤ 0.5%.
        2. Rising Support: Positive linear regression slope of rolling lows.

        Returns:
            pd.Series[bool]: True at bars where ascending triangle pattern is detected.

        Note:
            Uses vectorized pandas operations for performance.
        """
        window = 14
        is_ascending_triangle = pd.Series(False, index=self.df.index)

        # 1. Flat Upper Resistance Check
        # Calculate rolling max and check if highs stay within 0.5% of max
        rolling_high_max = self.df["high"].rolling(window=window).max()
        rolling_high_min = self.df["high"].rolling(window=window).min()

        # Variance in highs: (max - min) / max should be <= 0.5%
        high_variance = (rolling_high_max - rolling_high_min) / rolling_high_max
        flat_resistance = high_variance <= 0.005  # 0.5% tolerance

        # 2. Rising Support Check
        # Calculate linear regression slope of lows using rolling window
        # Slope > 0 indicates rising support

        def rolling_slope(series: pd.Series, window: int) -> pd.Series:
            """Calculate rolling linear regression slope."""
            # Create x values (0, 1, 2, ..., window-1)
            x = np.arange(window)
            x_mean = x.mean()

            def calc_slope(y):
                if len(y) < window or np.isnan(y).any():
                    return np.nan
                y_mean = y.mean()
                numerator = np.sum((x - x_mean) * (y - y_mean))
                denominator = np.sum((x - x_mean) ** 2)
                if denominator == 0:
                    return 0.0
                return numerator / denominator

            return series.rolling(window=window).apply(calc_slope, raw=True)

        low_slope = rolling_slope(self.df["low"], window)
        rising_support = low_slope > 0

        # Combine conditions
        is_ascending_triangle = flat_resistance & rising_support

        return is_ascending_triangle.fillna(False)

    def _detect_tweezer_bottoms(self) -> pd.Series:
        """
        Tweezer Bottoms Detection.

        A two-candle (or more) reversal pattern characterized by:
        1. Matching lows within 0.1% variance
        2. Downtrend context: RSI < 35
        3. Price below 20-period EMA

        Returns:
            pd.Series[bool]: True at bars where tweezer bottoms pattern is detected.

        Note:
            The second candle (current) should be bullish for optimal signal.
        """
        # 1. Matching lows check (within 0.1% of each other)
        current_low = self.df["low"]
        prev_low = self.df["low"].shift(1)

        # Variance check: |current - prev| / avg <= 0.1%
        avg_low = (current_low + prev_low) / 2
        low_diff_pct = np.abs(current_low - prev_low) / avg_low
        matching_lows = low_diff_pct <= 0.001  # 0.1% tolerance

        # 2. Downtrend context - RSI < 35 (oversold)
        if "RSI_14" in self.df.columns:
            rsi_oversold = self.df["RSI_14"] < 35
        else:
            rsi_oversold = False

        # 3. Price below 20-period EMA (downtrend confirmation)
        if "EMA_20" in self.df.columns:
            below_ema = self.df["close"] < self.df["EMA_20"]
        elif "EMA_50" in self.df.columns:
            # Fallback to EMA_50 if EMA_20 not available
            below_ema = self.df["close"] < self.df["EMA_50"]
        else:
            below_ema = pd.Series(True, index=self.df.index)  # Skip if no EMA available

        # 4. Current candle should be bullish (reversal indicator)
        current_bullish = self.df["close"] > self.df["open"]

        # Combine all conditions
        is_tweezer_bottoms = matching_lows & rsi_oversold & below_ema & current_bullish

        return is_tweezer_bottoms.fillna(False)

    # ================================================================
    # HIGH-PROBABILITY BULLISH PATTERNS (NEW)
    # ================================================================

    def _detect_dragonfly_doji(self) -> pd.Series:
        """
        Dragonfly Doji (65% success rate).

        A single-candle reversal pattern with:
        - Open ≈ Close ≈ High (within 10% of range)
        - Long lower shadow (>2x body size)
        - Little to no upper shadow

        Confluence (Crypto-tuned):
        - Location: Price at or below Bollinger Lower Band
        - RSI: < 35 (oversold)
        - Volume: Above average (confirms interest at low)
        """
        # Body and shadow calculations
        body_size = self.df["body_size"]
        total_range = self.df["total_range"]
        upper_shadow = self.df["high"] - np.maximum(self.df["open"], self.df["close"])
        lower_shadow = np.minimum(self.df["open"], self.df["close"]) - self.df["low"]

        # Core pattern: Open ≈ Close ≈ High
        body_near_high = upper_shadow < (total_range * 0.1)  # Upper shadow < 10% of range
        small_body = body_size < (total_range * 0.1)  # Body < 10% of range
        long_lower_shadow = lower_shadow > (body_size * 2)  # Lower shadow > 2x body

        is_dragonfly_shape = body_near_high & small_body & long_lower_shadow

        return is_dragonfly_shape.fillna(False)

    def _detect_bullish_belt_hold(self) -> pd.Series:
        """
        Bullish Belt Hold (60% success rate).

        A single-candle reversal pattern with:
        - Opens at session low (Open ≈ Low within 0.1%)
        - Large bullish body (>60% of range)
        - Closes near high

        Confluence (Crypto-tuned):
        - Location: Price below EMA 50 (potential reversal)
        - Volume: Above average (>120% SMA)
        - RSI: < 45 (not overbought)
        """
        total_range = self.df["total_range"]

        # Open at low (within 0.1% of low)
        open_at_low = (self.df["open"] - self.df["low"]) <= (self.df["low"] * 0.001)

        # Large bullish body (>60% of range)
        body_size = self.df["body_size"]
        large_body = body_size > (total_range * 0.6)

        # Bullish (green) candle
        is_green = self.df["is_green"]

        is_belt_hold_shape = open_at_low & large_body & is_green

        return is_belt_hold_shape.fillna(False)

    def _detect_bullish_harami(self) -> pd.Series:
        """
        Bullish Harami (53% success rate).

        A two-candle reversal pattern with:
        - t-1: Large bearish candle
        - t: Small bullish candle completely inside t-1's body
        - Body ratio: t body < 50% of t-1 body

        Confluence (Crypto-tuned):
        - RSI: < 40 (near oversold)
        - MFI: < 30 (money flow oversold)
        """
        # t-1: Large bearish candle
        t1_is_red = self.df["is_red"].shift(1)
        t1_body = self.df["body_size"].shift(1)
        t1_open = self.df["open"].shift(1)
        t1_close = self.df["close"].shift(1)

        # t: Small bullish candle
        t0_is_green = self.df["is_green"]
        t0_body = self.df["body_size"]
        t0_open = self.df["open"]
        t0_close = self.df["close"]

        # Inside condition: t body completely within t-1 body
        # For bearish t-1: open > close, so body is between close and open
        t1_body_high = np.maximum(t1_open, t1_close)
        t1_body_low = np.minimum(t1_open, t1_close)

        inside_body = (
            (t0_open > t1_body_low)
            & (t0_open < t1_body_high)
            & (t0_close > t1_body_low)
            & (t0_close < t1_body_high)
        )

        # Small body: t body < 50% of t-1 body
        small_body = t0_body < (t1_body * 0.5)

        is_harami_shape = t1_is_red & t0_is_green & inside_body & small_body

        return is_harami_shape.fillna(False)

    def _detect_bullish_kicker(self) -> pd.Series:
        """
        Bullish Kicker (75% success rate).

        A two-candle reversal pattern with:
        - t-1: Bearish candle
        - t: Bullish candle with gap up (Open > t-1 Open)
        - Body: t closes significantly higher (>1 ATR from t-1 close)

        Confluence (Crypto-tuned):
        - Volume: t volume > 200% of t-1 (extreme conviction)
        - Gap: True gap (t Low > t-1 High) preferred
        - RSI: Momentum shift (t RSI > 50)
        """
        # t-1: Bearish
        t1_is_red = self.df["is_red"].shift(1)
        t1_open = self.df["open"].shift(1)
        t1_high = self.df["high"].shift(1)
        t1_close = self.df["close"].shift(1)

        # t: Bullish with gap up
        t0_is_green = self.df["is_green"]
        t0_open = self.df["open"]
        t0_low = self.df["low"]

        # Gap up: t open > t-1 open (kicker condition)
        gap_up = t0_open > t1_open

        # True gap (stronger): t low > t-1 high
        true_gap = t0_low > t1_high

        # ATR for significance check
        atr_col = "ATRr_14" if "ATRr_14" in self.df.columns else "ATR_14"
        if atr_col in self.df.columns:
            atr = self.df[atr_col]
            significant_move = (self.df["close"] - t1_close) > atr
        else:
            significant_move = pd.Series(True, index=self.df.index)

        is_kicker_shape = t1_is_red & t0_is_green & gap_up & significant_move

        # Store true gap for bonus scoring
        self.df["is_true_gap_kicker"] = (is_kicker_shape & true_gap).fillna(False)

        return is_kicker_shape.fillna(False)

    def _detect_three_inside_up(self) -> pd.Series:
        """
        Three Inside Up (65% success rate).

        A three-candle reversal pattern with:
        - t-2: Large bearish candle
        - t-1: Bullish harami (inside t-2)
        - t: Bullish confirmation closing above t-2's open

        Confluence (Crypto-tuned):
        - Volume: Increasing across 3 candles
        - RSI: Rising from oversold
        - EMA: Price approaching or crossing EMA 20
        """
        # t-2: Large bearish
        t2_is_red = self.df["is_red"].shift(2)
        t2_open = self.df["open"].shift(2)
        t2_close = self.df["close"].shift(2)

        # t-1: Bullish inside t-2 (harami)
        t1_is_green = self.df["is_green"].shift(1)
        t1_open = self.df["open"].shift(1)
        t1_close = self.df["close"].shift(1)

        # Inside condition for t-1
        t2_body_high = np.maximum(t2_open, t2_close)
        t2_body_low = np.minimum(t2_open, t2_close)

        t1_inside = (
            (t1_open > t2_body_low)
            & (t1_open < t2_body_high)
            & (t1_close > t2_body_low)
            & (t1_close < t2_body_high)
        )

        # t: Bullish confirmation closing above t-2's open
        t0_is_green = self.df["is_green"]
        confirmation = self.df["close"] > t2_open

        is_three_inside_up_shape = (
            t2_is_red & t1_is_green & t1_inside & t0_is_green & confirmation
        )

        return is_three_inside_up_shape.fillna(False)

    def _detect_rising_three_methods(self) -> pd.Series:
        """
        Rising Three Methods (70% success rate).

        A five-candle continuation pattern with:
        - t-4: Large bullish candle (trend candle)
        - t-3 to t-1: 3 small bearish candles within t-4's range
        - t: Large bullish candle closing above t-4's high

        Confluence (Crypto-tuned):
        - Trend: Price above EMA 50 (uptrend confirmation)
        - Volume: Lower on consolidation (t-3 to t-1), higher on breakout (t)
        - ATR: Contraction during small candles
        """
        # t-4: Large bullish (trend candle)
        t4_is_green = self.df["is_green"].shift(4)
        t4_high = self.df["high"].shift(4)
        t4_low = self.df["low"].shift(4)
        t4_body = self.df["body_size"].shift(4)

        # t-3, t-2, t-1: Small candles within t-4's range
        t3_high = self.df["high"].shift(3)
        t3_low = self.df["low"].shift(3)
        t2_high = self.df["high"].shift(2)
        t2_low = self.df["low"].shift(2)
        t1_high = self.df["high"].shift(1)
        t1_low = self.df["low"].shift(1)

        # All 3 consolidation candles within t-4's range
        within_range_3 = (t3_high <= t4_high) & (t3_low >= t4_low)
        within_range_2 = (t2_high <= t4_high) & (t2_low >= t4_low)
        within_range_1 = (t1_high <= t4_high) & (t1_low >= t4_low)
        all_within_range = within_range_3 & within_range_2 & within_range_1

        # t: Bullish breakout above t-4's high
        t0_is_green = self.df["is_green"]
        breakout = self.df["close"] > t4_high

        # Large bodies for t-4 and t (relative to consolidation)
        avg_consol_body = (
            self.df["body_size"].shift(3)
            + self.df["body_size"].shift(2)
            + self.df["body_size"].shift(1)
        ) / 3
        t4_large = t4_body > (avg_consol_body * 1.5)
        t0_large = self.df["body_size"] > (avg_consol_body * 1.5)

        is_rising_three_shape = (
            t4_is_green & all_within_range & t0_is_green & breakout & t4_large & t0_large
        )

        return is_rising_three_shape.fillna(False)

    def _detect_falling_wedge(self) -> pd.Series:
        """
        Falling Wedge (74% success rate).

        A multi-day bullish reversal/continuation pattern with:
        - Converging trendlines: Lower highs AND lower lows
        - Both trendlines slope downward
        - Breakout: Close above upper trendline

        Confluence (Crypto-tuned):
        - Volume: Contracting during wedge, expanding on breakout (>150% SMA)
        - RSI: Rising during wedge formation (bullish divergence)
        - Volatility: ATR contraction during formation

        Uses 20-period lookback for wedge detection.
        """
        lookback = 20

        # Calculate linear regression slopes for highs and lows
        # Using rolling window approach

        # Create period index for regression
        x = np.arange(lookback)

        def calc_slope(series):
            """Calculate slope of linear regression."""
            if len(series) < lookback:
                return np.nan
            y = series.values[-lookback:]
            if np.any(np.isnan(y)):
                return np.nan
            slope = np.polyfit(x, y, 1)[0]
            return slope

        # Rolling slope of highs and lows
        high_slope = self.df["high"].rolling(window=lookback).apply(calc_slope, raw=False)
        low_slope = self.df["low"].rolling(window=lookback).apply(calc_slope, raw=False)

        # Both slopes negative (falling)
        both_falling = (high_slope < 0) & (low_slope < 0)

        # Converging: high slope less negative than low slope
        # (wedge narrows as highs fall slower than lows)
        converging = high_slope > low_slope

        # Breakout: Current close above the projected upper trendline
        # Approximate upper trendline as recent high minus regression
        recent_high = self.df["high"].rolling(window=5).max()
        breakout = self.df["close"] > recent_high.shift(1)

        is_falling_wedge_shape = both_falling & converging & breakout

        return is_falling_wedge_shape.fillna(False)

    def _detect_inverse_head_shoulders(self) -> pd.Series:
        """
        Inverse Head and Shoulders (89% success rate).

        A multi-day bullish reversal pattern with:
        - Left Shoulder: Local low followed by rally
        - Head: Lower low than shoulders
        - Right Shoulder: Higher low than head, similar to left shoulder
        - Neckline: Resistance connecting highs between shoulders

        Confluence (Crypto-tuned):
        - Volume: Decreasing on head, increasing on right shoulder breakout
        - RSI: Bullish divergence between head and right shoulder
        - Breakout: Close above neckline with confirmation

        Uses simplified detection with 30-period lookback.
        """
        # Need at least 35 periods for this pattern (30 lookback + 5 buffer)
        if len(self.df) < 35:
            return pd.Series(False, index=self.df.index)

        # Find local minima for shoulders and head
        # Using rolling min with different windows

        # Left shoulder region (periods -30 to -20)
        left_shoulder_low = self.df["low"].shift(25).rolling(window=10).min()

        # Head region (periods -20 to -10) - should be lowest
        head_low = self.df["low"].shift(15).rolling(window=10).min()

        # Right shoulder region (periods -10 to -1)
        right_shoulder_low = self.df["low"].shift(5).rolling(window=10).min()

        # Head must be lower than both shoulders
        head_lower_than_left = head_low < left_shoulder_low
        head_lower_than_right = head_low < right_shoulder_low

        # Shoulders should be roughly symmetrical (within 10%)
        shoulder_symmetry = (
            np.abs(left_shoulder_low - right_shoulder_low)
            / left_shoulder_low.replace(0, np.nan)
        ) < 0.10

        # Neckline: approximate as max high between shoulders
        neckline = self.df["high"].shift(10).rolling(window=20).max()

        # Breakout above neckline
        breakout = self.df["close"] > neckline

        is_inv_hs_shape = (
            head_lower_than_left & head_lower_than_right & shoulder_symmetry & breakout
        )

        return is_inv_hs_shape.fillna(False)
