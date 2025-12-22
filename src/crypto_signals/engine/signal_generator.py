"""
Signal Generator Module.

This module orchestrates the fetching of market data, application of technical
indicators, and detection of price patterns to generate trading signals.
"""

from typing import Optional, Type

import numpy as np
import pandas as pd
from crypto_signals.analysis.indicators import TechnicalIndicators
from crypto_signals.analysis.patterns import PatternAnalyzer
from crypto_signals.domain.schemas import (
    AssetClass,
    ExitReason,
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
        self,
        symbol: str,
        asset_class: AssetClass,
        dataframe: Optional[pd.DataFrame] = None,
    ) -> Optional[Signal]:
        """
        Generate a trading signal for a given symbol if a pattern is detected.

        Process:
        1. Fetch 365 days of daily bars (if not provided).
        2. Add technical indicators.
        3. Analyze for patterns.
        4. Construct a Signal object if a pattern is confirmed.

        Args:
            symbol: Ticker symbol (e.g. "BTC/USD", "AAPL").
            asset_class: Asset class for the symbol.
            dataframe: Optional cached dataframe to avoid redundant fetching.

        Returns:
            Signal: Validated signal object if a pattern is found, else None.
        """
        # 1. Fetch Data
        if dataframe is not None:
            df = dataframe
        else:
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

        # Confluence Factors: Scan for boolean flags
        # Confluence Factors: Scan for boolean flags in whitelist
        CONFLUENCE_WHITELIST = [
            "rsi_bullish_divergence",
            "vcp_filter",
            "volume_confirmed",
            "ema_cross_bullish",
            "macd_bullish_cross",
        ]

        confluence_factors = [
            col
            for col in CONFLUENCE_WHITELIST
            if col in latest.index
            and isinstance(latest[col], (bool, np.bool_))
            and latest[col]
        ]

        return Signal(
            signal_id=sig_id,
            strategy_id=strategy_id,
            symbol=symbol,
            ds=ds,
            asset_class=asset_class,
            confluence_factors=confluence_factors,
            entry_price=entry_ref,
            pattern_name=pattern_name,
            status=SignalStatus.WAITING,
            suggested_stop=suggested_stop,
            invalidation_price=invalidation_price,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            take_profit_3=take_profit_3,
        )

    def check_exits(
        self,
        active_signals: list[Signal],
        symbol: str,
        asset_class: AssetClass,
        dataframe: Optional[pd.DataFrame] = None,
    ) -> list[Signal]:
        """
        Check active signals for exit conditions (Profit or Invalidation).

        Exit Rules:
        1. Take Profit: Latest High >= Signal.take_profit_1/2
        2. Structural Invalidation: Latest Close < Signal.invalidation_price
        3. Color Flip: Latest candle is a Bearish Engulfing candle.
        4. Hard Sells: RSI > 80 or ADX Peaking.
        """
        # 1. Fetch Data
        if dataframe is not None:
            df = dataframe
        else:
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
        exited_signals = []

        # Current Candle Metrics
        current_high = float(latest["high"])
        current_close = float(latest["close"])

        # Chandelier Exit for Runner
        chandelier_exit = (
            float(latest["CHANDELIER_EXIT_LONG"])
            if "CHANDELIER_EXIT_LONG" in latest
            else None
        )

        # Invalidation triggers
        is_bearish_engulfing = latest.get("bearish_engulfing", False)

        # Check RSI > 80
        rsi_val = latest.get("RSI_14", 50)
        if pd.isna(rsi_val):
            rsi_val = 50
        rsi_overbought = rsi_val > 80

        # Check ADX Peaking
        adx_val = latest.get("ADX_14", 0)
        # Get prev row
        if len(analyzed_df) > 1:
            prev = analyzed_df.iloc[-2]
            adx_prev = prev.get("ADX_14", 0)
        else:
            adx_prev = 0

        adx_peaking = (adx_val > 50) and (adx_val < adx_prev)

        for signal in active_signals:
            exit_triggered = False

            # --- PROFIT TAKING ---

            # Check TP3 (Runner) - Chandelier Exit
            if chandelier_exit and current_close < chandelier_exit:
                if current_close > signal.entry_price:
                    signal.status = SignalStatus.TP3_HIT
                    signal.exit_reason = ExitReason.TP_HIT
                else:
                    signal.status = SignalStatus.INVALIDATED
                    signal.exit_reason = ExitReason.STOP_LOSS
                exit_triggered = True

            # Check TP2
            # Guard: Don't trigger if already TP2 or higher (though list filter handles TP3)
            elif (
                signal.take_profit_2
                and current_high >= signal.take_profit_2
                and signal.status != SignalStatus.TP2_HIT
            ):
                signal.status = SignalStatus.TP2_HIT
                signal.exit_reason = ExitReason.TP2
                exit_triggered = True

            # Check TP1
            # Guard: Only trigger if WAITING.
            # If already TP1_HIT, we want to skip this and check TP2 (handled above).
            elif (
                signal.take_profit_1
                and current_high >= signal.take_profit_1
                and signal.status == SignalStatus.WAITING
            ):
                signal.status = SignalStatus.TP1_HIT
                signal.suggested_stop = signal.entry_price
                signal.exit_reason = ExitReason.TP1
                exit_triggered = True

            # --- INVALIDATION ---
            if not exit_triggered:
                # 1. Structural Invalidation
                if (
                    signal.invalidation_price
                    and current_close < signal.invalidation_price
                ):
                    signal.status = SignalStatus.INVALIDATED
                    signal.exit_reason = ExitReason.STRUCTURAL_INVALIDATION
                    exit_triggered = True

                # 2. Dynamic Invalidation (Color Flip / Indicators)
                elif is_bearish_engulfing or rsi_overbought or adx_peaking:
                    signal.status = SignalStatus.INVALIDATED
                    signal.exit_reason = ExitReason.COLOR_FLIP
                    exit_triggered = True

            if exit_triggered:
                exited_signals.append(signal)

        return exited_signals
