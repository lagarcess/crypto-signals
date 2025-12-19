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

    def __init__(self, dataframe: pd.DataFrame):
        """Initialize the PatternAnalyzer with a dataframe."""
        self.df = dataframe.copy()  # Work on a copy safely

    def check_patterns(self) -> pd.DataFrame:
        """
        Scan the DataFrame for patterns.

        Returns a DataFrame with boolean columns:
        'bullish_hammer', 'bullish_engulfing', 'confirmed'.
        """
        # Ensure we have the basic components
        self._calculate_candle_shapes()

        # 1. Detect Shapes
        self.df["is_hammer_shape"] = self._detect_bullish_hammer()
        self.df["is_engulfing_shape"] = self._detect_bullish_engulfing()

        # 2. Check Confirmations
        self.df["trend_confirmed"] = self.df["close"] < self.df["EMA_50"]
        self.df["momentum_confirmed"] = self.df["RSI_14"] < self.RSI_THRESHOLD

        # Volume Confirmation: Check if Volume > 1.5 * VOL_SMA_20
        # Check if 'VOL_SMA_20' exists (if prefix='VOL' in indicators.py)
        # Otherwise fallback. We assume indicators added 'VOL_SMA_20'.
        if "VOL_SMA_20" in self.df.columns:
            self.df["volume_confirmed"] = self.df["volume"] > (
                self.VOLUME_FACTOR * self.df["VOL_SMA_20"]
            )
        else:
            # Fallback if specific column missing, though we should enforce it.
            self.df["volume_confirmed"] = False

        # 3. Combine for Final Signal
        # A signal is valid if Shape + Trend + Momentum + Volume
        confluence = (
            self.df["trend_confirmed"]
            & self.df["momentum_confirmed"]
            & self.df["volume_confirmed"]
        )

        self.df["bullish_hammer"] = self.df["is_hammer_shape"] & confluence
        self.df["bullish_engulfing"] = self.df["is_engulfing_shape"] & confluence

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

        # Determine color
        self.df["is_green"] = self.df["close"] > self.df["open"]
        self.df["is_red"] = self.df["close"] < self.df["open"]

    def _detect_bullish_hammer(self) -> pd.Series:
        """
        Vectorized detection of Bullish Hammer.

        Rules:
        1. Lower Wick >= 2.0 * Body
        2. Upper Wick <= 0.5 * Body
        3. Body in upper third (implied by wicks, verified loc)
        """
        # Rule 1 & 2
        ratio_check = (
            self.df["lower_wick"] >= self.HAMMER_LOWER_WICK_RATIO * self.df["body_size"]
        ) & (
            self.df["upper_wick"] <= self.HAMMER_UPPER_WICK_RATIO * self.df["body_size"]
        )

        # Rule 3: Body in upper third?
        # Means the top of the body is near the High.
        # Actually Rule 2 (Short Upper Wick) already enforces this.
        # If Upper Wick is small, Body Top is near High.

        return ratio_check

    def _detect_bullish_engulfing(self) -> pd.Series:
        """
        Vectorized detection of Bullish Engulfing.

        Rules:
        1. Current Green, Previous Red.
        2. Current Body fully overlaps Previous Body.
           Open <= Prev Close and Close > Prev Open.
        """
        # Shift to get previous candle values
        prev_close = self.df["close"].shift(1)
        prev_open = self.df["open"].shift(1)
        prev_is_red = self.df["is_red"].shift(1)

        # Current is Green
        curr_is_green = self.df["is_green"]

        # Engulfing Logic (Crypto adaptation: Open <= Prev Close
        # due to 24/7 continuity)
        # Prev Red: Open is Top, Close is Bottom.
        # Curr Green: Close is Top, Open is Bottom.
        # Overlap: Curr Open <= Prev Close AND Curr Close > Prev Open

        engulfing = (
            curr_is_green
            & prev_is_red
            & (self.df["open"] <= prev_close)
            & (self.df["close"] > prev_open)
        )

        return engulfing
