"""
Signal Generator Module.

This module orchestrates the fetching of market data, application of technical
indicators, and detection of price patterns to generate trading signals.
"""

from typing import Optional, Type

import pandas as pd
from crypto_signals.analysis.indicators import TechnicalIndicators
from crypto_signals.analysis.patterns import PatternAnalyzer
from crypto_signals.domain.schemas import (
    AssetClass,
    Signal,
    SignalStatus,
    get_deterministic_id,
)
from crypto_signals.market.data_provider import MarketDataProvider


class SignalGenerator:
    """Orchestrates signal generation from market data."""

    def __init__(
        self,
        market_provider: MarketDataProvider,
        indicators: Optional[TechnicalIndicators] = None,
        pattern_analyzer_cls: Type[PatternAnalyzer] = PatternAnalyzer,
    ):
        """
        Initialize the SignalGenerator.

        Args:
            market_provider: Provider for fetching market data.
            indicators: Instance for adding technical indicators (dependency
                injection). Defaults to new TechnicalIndicators instance.
            pattern_analyzer_cls: Class for verifying patterns (dependency
                injection).
        """
        self.market_provider = market_provider
        self.indicators = indicators or TechnicalIndicators()
        self.pattern_analyzer_cls = pattern_analyzer_cls

    def generate_signals(
        self, symbol: str, asset_class: AssetClass
    ) -> Optional[Signal]:
        """
        Generate a trading signal for a given symbol if a pattern is detected.

        Process:
        1. Fetch 365 days of daily bars.
        2. Add technical indicators.
        3. Analyze for patterns.
        4. Construct a Signal object if a pattern is confirmed.

        Args:
            symbol: Ticker symbol (e.g. "BTC/USD", "AAPL").
            asset_class: Asset class for the symbol.

        Returns:
            Signal: Validated signal object if a pattern is found, else None.
        """
        # 1. Fetch Data
        df = self.market_provider.get_daily_bars(
            symbol=symbol, asset_class=asset_class, lookback_days=365
        )

        if df.empty:
            return None

        # 2. Add Indicators
        self.indicators.add_all_indicators(df)

        # 3. Analyze Patterns
        analyzer = self.pattern_analyzer_cls(dataframe=df)
        analyzed_df = analyzer.check_patterns()

        if analyzed_df.empty:
            return None

        # Check the LATEST completed candle (last row)
        latest = analyzed_df.iloc[-1]

        pattern_name = None

        # Check patterns in order of priority
        if latest.get("bull_flag"):
            pattern_name = "BULL_FLAG"
        elif latest.get("three_white_soldiers"):
            pattern_name = "THREE_WHITE_SOLDIERS"
        elif latest.get("bullish_marubozu"):
            pattern_name = "BULLISH_MARUBOZU"
        elif latest.get("morning_star"):
            pattern_name = "MORNING_STAR"
        elif latest.get("piercing_line"):
            pattern_name = "PIERCING_LINE"
        elif latest.get("bullish_engulfing"):
            pattern_name = "BULLISH_ENGULFING"
        elif latest.get("bullish_hammer"):
            pattern_name = "BULLISH_HAMMER"
        elif latest.get("inverted_hammer"):
            pattern_name = "INVERTED_HAMMER"
        elif latest.get("double_bottom"):
            pattern_name = "DOUBLE_BOTTOM"

        if not pattern_name:
            return None

        # 4. Construct Signal
        sig_id = get_deterministic_id(f"{symbol}|{pattern_name}|{latest.name}")

        return self._create_signal(
            symbol,
            asset_class,
            pattern_name,
            latest,
            sig_id,
        )

    def _create_signal(
        self,
        symbol: str,
        asset_class: AssetClass,
        pattern_name: str,
        latest: pd.Series,
        sig_id: str,
    ) -> Signal:
        """Create a Signal object with all fields populated."""
        # Ensure we have a date object (for logging context if needed)
        # signal_date = (
        #     latest.name.date()
        #     if hasattr(latest.name, "date")
        #     else latest.name
        # )

        # Extract Prices
        close_price = float(latest["close"])
        low_price = float(latest["low"])
        open_price = float(latest["open"])

        # ATR for Dynamic Exits
        atr = float(latest["ATRr_14"]) if "ATRr_14" in latest else 0.0
        if atr == 0.0 and "ATR_14" in latest:
            atr = float(latest["ATR_14"])

        # --- Exit Logic ---

        # 1. Invalidation (Stop Loss)
        # Default: 1% below Low
        suggested_stop = low_price * 0.99
        invalidation_price = None

        # Specific Structural Invalidation
        if pattern_name == "BULLISH_HAMMER":
            # Invalidation: Close below candle low
            invalidation_price = low_price
            suggested_stop = invalidation_price * 0.99

        elif pattern_name == "BULLISH_ENGULFING":
            # Invalidation: Close below Open of engulfing candle
            invalidation_price = open_price
            suggested_stop = invalidation_price * 0.99

        if pattern_name == "MORNING_STAR":
            # Exit on close below low of t2 (the star).
            # We access t-1 low relative to current (t0).
            # Need to get the row before? Vectorized approach:
            # We generated signals on the last row.
            pass  # Logic requires lookback context not currently in 'latest'

        elif pattern_name == "BULLISH_MARUBOZU":
            # Exit below 50% of body
            midpoint = (open_price + close_price) / 2
            invalidation_price = midpoint
            suggested_stop = invalidation_price * 0.99  # Marubozu fail is strict

        elif pattern_name == "BULL_FLAG":
            # Below lower channel... implies below recent low.
            # Use general stop for now.
            pass

        # 2. Take Profits (ATR Based)
        # Entry assumed at Close (or next Open, but Close is known)
        entry_ref = close_price

        take_profit_1 = entry_ref + (2.0 * atr) if atr > 0 else None
        take_profit_2 = entry_ref + (4.0 * atr) if atr > 0 else None
        # TP3: Runner (Moonbag) -> Chandelier Exit value at entry?
        # Ideally, this updates dynamically, but we can store the
        # initial trailing stop level.
        take_profit_3 = (
            float(latest["CHANDELIER_EXIT_LONG"])
            if "CHANDELIER_EXIT_LONG" in latest
            else None
        )

        # Strategy ID is the pattern name for now
        strategy_id = pattern_name

        # DS is the date component of the timestamp
        ds = latest.name.date() if hasattr(latest.name, "date") else latest.name

        return Signal(
            signal_id=sig_id,
            strategy_id=strategy_id,
            symbol=symbol,
            ds=ds,
            pattern_name=pattern_name,
            status=SignalStatus.WAITING,
            suggested_stop=suggested_stop,
            invalidation_price=invalidation_price,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            take_profit_3=take_profit_3,
        )

    def check_invalidation(
        self,
        active_signals: list[Signal],
        symbol: str,
        asset_class: AssetClass,
    ) -> list[Signal]:
        """
        Check active signals for invalidation conditions.

        Invalidation Rules:
        1. Structural Invalidation: Latest Close < Signal.invalidation_price
        2. Color Flip: Latest candle is a Bearish Engulfing candle.
        3. Hard Sells: RSI > 80.
        """
        # 1. Fetch Data
        df = self.market_provider.get_daily_bars(
            symbol=symbol, asset_class=asset_class, lookback_days=365
        )
        if df.empty:
            return []

        # 2. Add Indicators & Patterns
        self.indicators.add_all_indicators(df)
        analyzer = self.pattern_analyzer_cls(dataframe=df)
        analyzed_df = analyzer.check_patterns()

        if analyzed_df.empty:
            return []

        latest = analyzed_df.iloc[-1]
        invalidated_signals = []

        is_bearish_engulfing = latest.get("bearish_engulfing", False)
        # Check RSI > 80
        rsi_val = latest.get("RSI_14", 50)
        # Handle if RSI is NaN
        if pd.isna(rsi_val):
            rsi_val = 50
        rsi_overbought = rsi_val > 80

        # Check ADX Peaking (ADX > 50 and turning down)
        # Need previous ADX
        adx_val = latest.get("ADX_14", 0)
        # Get prev row
        if len(analyzed_df) > 1:
            prev = analyzed_df.iloc[-2]
            adx_prev = prev.get("ADX_14", 0)
        else:
            adx_prev = 0

        adx_peaking = (adx_val > 50) and (adx_val < adx_prev)

        for signal in active_signals:
            is_invalid = False

            # Confirm: Today's Close > Hammer Body (t-1).
            # Hammer Body High = max(open, close) of t-1
            # Note: self.df is not available here, assuming 'df' was intended
            # This logic seems misplaced for invalidation check of active signals
            # and contains a syntax error in the original request.
            # The line below is syntactically corrected based on the likely intent
            # but its logical placement might be incorrect for this method.
            # body_high_prev = np.maximum(df["open"].shift(1), df["close"].shift(1))
            # is_confirmed = df["close"].iloc[-1] > body_high_prev.iloc[-1] # Example correction

            # 1. Structural Invalidation
            # If invalidation_price is set, and Close < Price
            if (
                signal.invalidation_price
                and latest["close"] < signal.invalidation_price
            ):
                is_invalid = True
            # 2. Color Flip / Bearish Engulfing / Hard Sell (RSI / ADX)
            elif is_bearish_engulfing or rsi_overbought or adx_peaking:
                is_invalid = True

            if is_invalid:
                invalidated_signals.append(signal)

        return invalidated_signals
