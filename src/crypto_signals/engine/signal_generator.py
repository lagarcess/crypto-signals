"""
Signal Generator Module.

This module orchestrates the fetching of market data, application of technical
indicators, and detection of price patterns to generate trading signals.
"""

from typing import Optional, Type

import numpy as np
import pandas as pd
from crypto_signals.analysis.indicators import TechnicalIndicators
from crypto_signals.analysis.patterns import (
    PatternAnalyzer,
)
from crypto_signals.domain.schemas import (
    AssetClass,
    ExitReason,
    OrderSide,
    Signal,
    SignalStatus,
    get_deterministic_id,
)
from crypto_signals.market.data_provider import MarketDataProvider
from loguru import logger


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

        # Check patterns in order of priority (Highest Historical Success First)
        if latest.get("inverse_head_shoulders"):
            pattern_name = "INVERSE_HEAD_SHOULDERS"  # 89%
        elif latest.get("bullish_kicker"):
            pattern_name = "BULLISH_KICKER"  # 75%
        elif latest.get("falling_wedge"):
            pattern_name = "FALLING_WEDGE"  # 74%
        elif latest.get("rising_three_methods"):
            pattern_name = "RISING_THREE_METHODS"  # 70%
        elif latest.get("morning_star"):
            pattern_name = "MORNING_STAR"  # 70%
        elif latest.get("ascending_triangle"):
            pattern_name = "ASCENDING_TRIANGLE"  # 68%
        elif latest.get("three_inside_up"):
            pattern_name = "THREE_INSIDE_UP"  # 65%
        elif latest.get("dragonfly_doji"):
            pattern_name = "DRAGONFLY_DOJI"  # 65%
        elif latest.get("three_white_soldiers"):
            pattern_name = "THREE_WHITE_SOLDIERS"  # 64%
        elif latest.get("cup_and_handle"):
            pattern_name = "CUP_AND_HANDLE"  # 63%
        elif latest.get("double_bottom"):
            pattern_name = "DOUBLE_BOTTOM"  # 62%
        elif latest.get("bull_flag"):
            pattern_name = "BULL_FLAG"  # 61%
        elif latest.get("bullish_belt_hold"):
            pattern_name = "BULLISH_BELT_HOLD"  # 60%
        elif latest.get("bullish_engulfing"):
            pattern_name = "BULLISH_ENGULFING"  # 58%
        elif latest.get("bullish_hammer"):
            pattern_name = "BULLISH_HAMMER"  # 57%
        elif latest.get("piercing_line"):
            pattern_name = "PIERCING_LINE"  # 55%
        elif latest.get("inverted_hammer"):
            pattern_name = "INVERTED_HAMMER"  # 55%
        elif latest.get("bullish_marubozu"):
            pattern_name = "BULLISH_MARUBOZU"  # 54%
        elif latest.get("bullish_harami"):
            pattern_name = "BULLISH_HARAMI"  # 53%
        elif latest.get("tweezer_bottoms"):
            pattern_name = "TWEEZER_BOTTOMS"  # 52%

        if not pattern_name:
            return None

        # ============================================================
        # SIGNAL QUALITY FILTERS (Confluence Validation)
        # ============================================================
        # Collect all rejection reasons and indicator values for transparency
        rejection_reasons: list[str] = []

        # Extract indicator values for confluence snapshot
        current_volume = float(latest.get("volume", 0))
        vol_sma_20 = float(latest.get("VOL_SMA_20", 1.0))
        if vol_sma_20 <= 0:
            vol_sma_20 = 1.0
        volume_ratio = current_volume / vol_sma_20 if vol_sma_20 > 0 else 0

        rsi_value = float(latest.get("RSI_14", 50))  # Default to neutral
        adx_value = float(latest.get("ADX_14", 25))  # Default to moderate trend
        sma_200 = float(latest.get("SMA_200", 0))
        close_price = float(latest.get("close", 0))
        sma_trend = "Above" if close_price > sma_200 and sma_200 > 0 else "Below"

        # Define pattern categories for targeted validation
        breakout_patterns = (
            "ASCENDING_TRIANGLE",
            "CUP_AND_HANDLE",
            "FALLING_WEDGE",
            "INVERSE_HEAD_SHOULDERS",
            "BULL_FLAG",
            "DOUBLE_BOTTOM",
            "BULLISH_MARUBOZU",
        )
        trend_following_patterns = (
            "BULL_FLAG",
            "ASCENDING_TRIANGLE",
            "RISING_THREE_METHODS",
            "THREE_WHITE_SOLDIERS",
        )

        # 1. VOLUME CONFIRMATION FILTER (Breakout patterns only)
        if pattern_name in breakout_patterns and volume_ratio < 1.5:
            rejection_reasons.append(f"Volume {volume_ratio:.1f}x < 1.5x")

        # 2. RSI OVERBOUGHT FILTER (Bullish patterns)
        # Reject if RSI > 70 (overbought) - reduces chasing extended moves
        if rsi_value > 70:
            rejection_reasons.append(f"RSI {rsi_value:.0f} > 70 (Overbought)")

        # 3. ADX WEAK TREND FILTER (Trend-following patterns only)
        # Reject if ADX < 20 - trend is too weak for trend-following setups
        if pattern_name in trend_following_patterns and adx_value < 20:
            rejection_reasons.append(f"ADX {adx_value:.0f} < 20 (Weak Trend)")

        # Build confluence snapshot for persistence
        confluence_snapshot = {
            "rsi": round(rsi_value, 1),
            "adx": round(adx_value, 1),
            "sma_trend": sma_trend,
            "volume_ratio": round(volume_ratio, 2),
        }

        # If quality gate failures exist at this point, reject early
        if rejection_reasons:
            combined_reason = " AND ".join(rejection_reasons)
            logger.warning(
                f"[REJECTION] {symbol} {pattern_name} rejected: {combined_reason}"
            )
            return self._create_rejected_signal(
                symbol,
                asset_class,
                pattern_name,
                latest,
                analyzer,
                combined_reason,
                confluence_snapshot,
            )

        # 4. Construct Signal
        sig_id = get_deterministic_id(f"{symbol}|{pattern_name}|{latest.name}")

        signal = self._create_signal(
            symbol,
            asset_class,
            pattern_name,
            latest,
            sig_id,
            analyzer,
        )

        # 5. RISK-TO-REWARD (R:R) FILTER (Post-construction)
        # Discard any signal where the R:R ratio is less than 1.5
        rr_ratio = 0.0
        if signal.take_profit_1 and signal.suggested_stop and signal.entry_price:
            potential_profit = abs(signal.take_profit_1 - signal.entry_price)
            potential_risk = abs(signal.entry_price - signal.suggested_stop)

            if potential_risk > 0:
                rr_ratio = potential_profit / potential_risk
                confluence_snapshot["rr_ratio"] = round(rr_ratio, 2)

                if rr_ratio < 1.5:
                    rejection_reason = f"R:R {rr_ratio:.1f} < 1.5"
                    logger.warning(
                        f"[REJECTION] {symbol} {pattern_name} rejected: {rejection_reason}"
                    )
                    return self._create_rejected_signal(
                        symbol,
                        asset_class,
                        pattern_name,
                        latest,
                        analyzer,
                        rejection_reason,
                        confluence_snapshot,
                    )

        return signal

    def _create_signal(
        self,
        symbol: str,
        asset_class: AssetClass,
        pattern_name: str,
        latest: pd.Series,
        sig_id: str,
        analyzer: PatternAnalyzer,
    ) -> Signal:
        """Create a Signal object with all fields populated, including structural metadata."""

        # Extract Prices
        close_price = float(latest["close"])
        low_price = float(latest["low"])
        open_price = float(latest["open"])

        # ATR for Dynamic Exits
        atr = float(latest["ATRr_14"]) if "ATRr_14" in latest else 0.0
        if atr == 0.0 and "ATR_14" in latest:
            atr = float(latest["ATR_14"])

        # Stop Loss: 1% below Low by default
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
            # Exit on close below low of the star candle.
            # The star is t-1 (middle candle of the 3-candle pattern).
            # Since we detect on the final candle (t0), use current low as conservative stop.
            # Full lookback would access df.iloc[-2]["low"] but 'latest' is a Series.
            invalidation_price = low_price
            suggested_stop = invalidation_price * 0.99

        elif pattern_name == "BULLISH_MARUBOZU":
            # Exit below 50% of body
            midpoint = (open_price + close_price) / 2
            invalidation_price = midpoint
            suggested_stop = invalidation_price * 0.99  # Marubozu fail is strict

        elif pattern_name == "BULL_FLAG":
            # Pattern-specific exits based on flagpole geometry
            # Calculate flagpole height from recent price action

            # Get pole high (recent high from rolling 15-day max)
            # and pole low (start of the move)
            pole_high = float(latest.get("high", close_price))
            pole_low = low_price  # Flag consolidation low

            # Estimate flagpole height (use volatility-adjusted calculation)
            # For Bull Flag, we look at the move that created the pole
            if "ATRr_14" in latest:
                # Flagpole is typically 2-4x ATR
                flagpole_height = max(atr * 3.0, pole_high - pole_low)
            else:
                flagpole_height = pole_high - pole_low

            # TP1 = 50% of flagpole height above breakout
            # TP2 = 100% of flagpole height above breakout
            take_profit_1 = close_price + (0.5 * flagpole_height)
            take_profit_2 = close_price + (1.0 * flagpole_height)

            # SL = below lowest low of flag consolidation
            invalidation_price = low_price
            suggested_stop = invalidation_price * 0.99

        # Take Profits (ATR Based)
        entry_ref = close_price

        take_profit_1 = entry_ref + (2.0 * atr) if atr > 0 else None
        take_profit_2 = entry_ref + (4.0 * atr) if atr > 0 else None
        # TP3: Extended runner target (becomes trailing stop after TP1/TP2 hit)
        # Initial target ensures TP3 > TP2 for clean signal display
        # After TP1/TP2, check_exits() updates this to Chandelier Exit for trailing
        take_profit_3 = entry_ref + (6.0 * atr) if atr > 0 else None

        # Strategy ID is the pattern name for now
        strategy_id = pattern_name

        # DS is the date component of the timestamp
        ds = latest.name.date() if hasattr(latest.name, "date") else latest.name

        # Confluence Factors: boolean flags in whitelist
        CONFLUENCE_WHITELIST = [
            "rsi_bullish_divergence",
            "volatility_contraction",
            "volume_expansion",
            "trend_bullish",
        ]

        confluence_factors = [
            col
            for col in CONFLUENCE_WHITELIST
            if col in latest.index
            and isinstance(latest[col], (bool, np.bool_))
            and latest[col]
        ]

        # ============================================================
        # STRUCTURAL METADATA EXTRACTION
        # ============================================================
        pattern_duration_days = None
        pattern_classification = None
        structural_anchors = None

        # Extract pattern-specific duration/classification from metadata columns
        # Map pattern names to their corresponding metadata column prefixes
        structural_patterns = {
            "DOUBLE_BOTTOM": "double_bottom",
            "INVERSE_HEAD_SHOULDERS": "inv_hs",
            "BULL_FLAG": "bull_flag",
            "CUP_AND_HANDLE": "cup_handle",
            "FALLING_WEDGE": "falling_wedge",
            "ASCENDING_TRIANGLE": "asc_triangle",
        }

        if pattern_name in structural_patterns:
            col_prefix = structural_patterns[pattern_name]
            duration_col = f"{col_prefix}_duration"
            class_col = f"{col_prefix}_classification"
            pivots_col = f"{col_prefix}_pivots"

            if duration_col in latest.index and pd.notna(latest.get(duration_col)):
                pattern_duration_days = int(latest[duration_col])

            if class_col in latest.index and pd.notna(latest.get(class_col)):
                pattern_classification = str(latest[class_col])

        # Extract structural pivots (limit to 5 most recent for memory efficiency)
        pattern_span_days = None
        if hasattr(analyzer, "pivots") and analyzer.pivots:
            # Get the 5 most recent pivots, sorted chronologically
            recent_pivots = sorted(analyzer.pivots[-5:], key=lambda p: p.index)

            structural_anchors = [
                {
                    "price": p.price,
                    "timestamp": str(p.timestamp) if p.timestamp else None,
                    "pivot_type": p.pivot_type,
                    "index": p.index,
                }
                for p in recent_pivots
            ]

            # Calculate pattern span (first to last pivot in the cluster)
            if len(structural_anchors) >= 2:
                pivot_indices = [p["index"] for p in structural_anchors]
                pattern_span_days = max(pivot_indices) - min(pivot_indices)

        # Classification Fix: MACRO only if pattern_span_days > 90 days
        # This overrides any classification from metadata columns
        if pattern_span_days is not None:
            if pattern_span_days > 90:
                pattern_classification = "MACRO_PATTERN"
            else:
                pattern_classification = "STANDARD_PATTERN"

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
            pattern_duration_days=pattern_duration_days,
            pattern_span_days=pattern_span_days,
            pattern_classification=pattern_classification,
            structural_anchors=structural_anchors,
        )

    def _create_rejected_signal(
        self,
        symbol: str,
        asset_class: AssetClass,
        pattern_name: str,
        latest: pd.Series,
        analyzer: PatternAnalyzer,
        rejection_reason: str,
        confluence_snapshot: dict | None = None,
    ) -> Signal:
        """Create a shadow signal for rejected patterns (failed quality gates).

        These signals have status REJECTED_BY_FILTER and are used for:
        - Firestore auditing (rejected_signals collection)
        - Discord shadow channel visibility
        - Phase 8 backtesting analysis

        Args:
            symbol: Trading symbol
            asset_class: Asset class (CRYPTO/EQUITY)
            pattern_name: Name of detected pattern
            latest: Latest candle data
            analyzer: Pattern analyzer with pivot data
            rejection_reason: Why the signal was rejected
            confluence_snapshot: Indicator values at rejection time
        """
        sig_id = get_deterministic_id(f"{symbol}|{pattern_name}|{latest.name}|REJECTED")

        # Create base signal with structural metadata
        signal = self._create_signal(
            symbol, asset_class, pattern_name, latest, sig_id, analyzer
        )

        # Override status and add rejection metadata
        signal.status = SignalStatus.REJECTED_BY_FILTER
        signal.rejection_reason = rejection_reason
        signal.confluence_snapshot = confluence_snapshot

        return signal

    def check_exits(
        self,
        active_signals: list[Signal],
        symbol: str,
        asset_class: AssetClass,
        dataframe: Optional[pd.DataFrame] = None,
    ) -> list[Signal]:
        """
        Check active signals for exit conditions and trailing stop updates.

        Returns signals requiring persistence updates, including:
        - Status changes (TP1/TP2/TP3 hits, invalidations)
        - Trailing stop updates for Runner positions (TP1_HIT or TP2_HIT status)

        Exit Rules:
        1. Take Profit: Latest High >= Signal.take_profit_1/2
        2. Structural Invalidation: Latest Close < Signal.invalidation_price
        3. Color Flip: Latest candle is a Bearish Engulfing candle.
        4. Hard Sells: RSI > 80 or ADX Peaking.

        Active Trailing (Runner Phase):
        - For signals in TP1_HIT or TP2_HIT, updates take_profit_3 when
          Chandelier Exit moves higher than current value.
        - Sets _trail_updated attribute to distinguish from status exits.
        - Sets _previous_tp3 attribute for notification threshold calculation.
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

        logger.debug(
            f"analyzed_df type={type(analyzed_df)}, "
            f"empty check: {getattr(analyzed_df, 'empty', 'N/A')}"
        )

        if analyzed_df.empty:
            logger.debug("analyzed_df is empty, returning early")
            return []

        latest = analyzed_df.iloc[-1]
        exited_signals = []

        # Current Candle Metrics
        current_high = float(latest["high"])
        current_low = float(latest["low"])
        current_close = float(latest["close"])

        logger.debug(
            f"check_exits: analyzed_df has {len(analyzed_df)} rows, "
            f"high={current_high}, low={current_low}, close={current_close}"
        )

        # Chandelier Exit for Runner (direction-aware)
        chandelier_exit_long = (
            float(latest["CHANDELIER_EXIT_LONG"])
            if "CHANDELIER_EXIT_LONG" in latest
            else None
        )
        chandelier_exit_short = (
            float(latest["CHANDELIER_EXIT_SHORT"])
            if "CHANDELIER_EXIT_SHORT" in latest
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
            trail_updated = False
            original_status = signal.status

            # Determine side once for this signal
            is_long = signal.side != OrderSide.SELL

            logger.debug(
                f"Processing signal {signal.signal_id}: status={signal.status}, "
                f"side={signal.side}, is_long={is_long}, tp1={signal.take_profit_1}, "
                f"tp2={signal.take_profit_2}, tp3={signal.take_profit_3}"
            )

            # --- ACTIVE TRAILING (Runner Phase) ---
            # For signals in TP1_HIT or TP2_HIT, update trailing stop
            # Long: trailing stop moves UP (chandelier_exit_long > current)
            # Short: trailing stop moves DOWN (chandelier_exit_short < current)
            if signal.status in (SignalStatus.TP1_HIT, SignalStatus.TP2_HIT):
                current_tp3 = signal.take_profit_3 or 0.0
                is_long = signal.side != OrderSide.SELL

                if is_long and chandelier_exit_long:
                    # Long: update if new trailing stop is HIGHER
                    # (initialization when current_tp3 == 0 is handled implicitly: any positive > 0)
                    if chandelier_exit_long > current_tp3:
                        object.__setattr__(signal, "_previous_tp3", current_tp3)
                        signal.take_profit_3 = chandelier_exit_long
                        trail_updated = True
                elif not is_long and chandelier_exit_short:
                    # Short: update if new trailing stop is LOWER
                    # For shorts, lower is better (locking in more profit as price falls)
                    # Initialization: when current_tp3 == 0, always set initial stop
                    # Trailing: only update if new stop is lower (more favorable)
                    should_update = (
                        current_tp3 == 0.0  # Initialization
                        or chandelier_exit_short < current_tp3  # Trailing down
                    )
                    if should_update:
                        object.__setattr__(signal, "_previous_tp3", current_tp3)
                        signal.take_profit_3 = chandelier_exit_short
                        trail_updated = True

            # --- PROFIT TAKING ---

            # Get appropriate chandelier exit based on side
            is_long = signal.side != OrderSide.SELL
            chandelier_exit = chandelier_exit_long if is_long else chandelier_exit_short

            # Check TP3 (Runner) - Chandelier Exit
            # Long: exit if close < chandelier (price fell below trailing stop)
            # Short: exit if close > chandelier (price rose above trailing stop)
            tp3_exit_triggered = False
            if chandelier_exit:
                if is_long and current_close < chandelier_exit:
                    tp3_exit_triggered = True
                elif not is_long and current_close > chandelier_exit:
                    tp3_exit_triggered = True

            if tp3_exit_triggered:
                # Determine if profitable
                is_profitable = (
                    (current_close > signal.entry_price)
                    if is_long
                    else (current_close < signal.entry_price)
                )
                if is_profitable:
                    signal.status = SignalStatus.TP3_HIT
                    signal.exit_reason = ExitReason.TP_HIT
                else:
                    signal.status = SignalStatus.INVALIDATED
                    signal.exit_reason = ExitReason.STOP_LOSS
                exit_triggered = True

            # Check TP2
            # Guard: Don't trigger if already TP2 or higher (though list filter handles TP3)
            # Long: price rises above TP2 (high >= target)
            # Short: price falls below TP2 (low <= target)
            if (
                not exit_triggered
                and signal.take_profit_2
                and signal.status != SignalStatus.TP2_HIT
            ):
                tp2_hit = False
                if is_long and current_high >= signal.take_profit_2:
                    tp2_hit = True
                elif not is_long and current_low <= signal.take_profit_2:
                    tp2_hit = True

                if tp2_hit:
                    signal.status = SignalStatus.TP2_HIT
                    signal.exit_reason = ExitReason.TP2
                    exit_triggered = True

            # Check TP1
            # Guard: Only trigger if WAITING.
            # If already TP1_HIT, we want to skip this and check TP2 (handled above).
            # Long: price rises above TP1 (high >= target)
            # Short: price falls below TP1 (low <= target)
            if (
                not exit_triggered
                and signal.take_profit_1
                and signal.status == SignalStatus.WAITING
            ):
                tp1_hit = False
                if is_long and current_high >= signal.take_profit_1:
                    tp1_hit = True
                elif not is_long and current_low <= signal.take_profit_1:
                    tp1_hit = True

                logger.debug(
                    f"TP1 check: is_long={is_long}, high={current_high}, "
                    f"tp1={signal.take_profit_1}, tp1_hit={tp1_hit}"
                )

                if tp1_hit:
                    signal.status = SignalStatus.TP1_HIT
                    signal.suggested_stop = signal.entry_price
                    signal.exit_reason = ExitReason.TP1
                    exit_triggered = True
                    logger.debug("TP1 HIT! exit_triggered=True")

            # --- INVALIDATION ---
            if not exit_triggered:
                # 1. Structural Invalidation
                # Long: price falls below invalidation level
                # Short: price rises above invalidation level
                invalidation_triggered = False
                if signal.invalidation_price:
                    if is_long and current_close < signal.invalidation_price:
                        invalidation_triggered = True
                    elif not is_long and current_close > signal.invalidation_price:
                        invalidation_triggered = True

                if invalidation_triggered:
                    signal.status = SignalStatus.INVALIDATED
                    signal.exit_reason = ExitReason.STRUCTURAL_INVALIDATION
                    exit_triggered = True

                # 2. Dynamic Invalidation (Color Flip / Indicators)
                # Note: bearish_engulfing, rsi_overbought, adx_peaking are Long-specific
                # For Short positions, these would indicate favorable conditions, not invalidation
                # NOTE: Bullish equivalents for Short invalidation not yet implemented.\n                # Short signals use structural invalidation only, not pattern-based exits\n                # (e.g., bullish_engulfing). This is a known Phase 8 enhancement.
                elif is_long and (is_bearish_engulfing or rsi_overbought or adx_peaking):
                    signal.status = SignalStatus.INVALIDATED
                    signal.exit_reason = ExitReason.COLOR_FLIP
                    exit_triggered = True

            # Include signal if exit triggered OR if trail updated
            logger.debug(
                f"End of loop: exit_triggered={exit_triggered}, trail_updated={trail_updated}"
            )
            if exit_triggered:
                # Detect Status Jump (e.g., WAITING -> TP2_HIT)
                if (
                    original_status == SignalStatus.WAITING
                    and signal.status == SignalStatus.TP2_HIT
                ):
                    logger.info(
                        f"Status Jump detected for {signal.signal_id}: WAITING -> TP2_HIT"
                    )
                    object.__setattr__(signal, "_status_jump", True)

                exited_signals.append(signal)
                logger.debug("Appended signal to exited_signals (exit_triggered)")
            elif trail_updated:
                # Mark for main.py to distinguish from status changes
                # Use object.__setattr__ to bypass Pydantic's validation
                object.__setattr__(signal, "_trail_updated", True)
                exited_signals.append(signal)
                logger.debug("Appended signal to exited_signals (trail_updated)")

        logger.debug(f"Returning {len(exited_signals)} exited signals")
        return exited_signals
