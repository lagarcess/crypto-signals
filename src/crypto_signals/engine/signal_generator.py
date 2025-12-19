"""
Signal Generator Module.

This module orchestrates the fetching of market data, application of technical
indicators, and detection of price patterns to generate trading signals.
"""

from typing import Optional, Type

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
        indicators: Type[TechnicalIndicators] = TechnicalIndicators,
        pattern_analyzer_cls: Type[PatternAnalyzer] = PatternAnalyzer,
    ):
        """
        Initialize the SignalGenerator.

        Args:
            market_provider: Provider for fetching market data.
            indicators: Class providing the `add_all_indicators` method used to
                apply all technical indicators (dependency injection).
            pattern_analyzer_cls: Class for verifying patterns (dependency
                injection).
        """
        self.market_provider = market_provider
        self.indicators = indicators
        self.pattern_analyzer_cls = pattern_analyzer_cls

    def generate_signals(
        self, symbol: str, asset_class: AssetClass
    ) -> Optional[Signal]:
        """
        Generate a trading signal for a given symbol if a pattern is detected.

        Process:
        1. Fetch 365 days of daily bars.
        2. Add technical indicators.
        3. Analyze for patterns (Bullish Hammer, Bullish Engulfing).
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
        df = self.indicators.add_all_indicators(df)

        # 3. Analyze Patterns
        analyzer = self.pattern_analyzer_cls(dataframe=df)
        analyzed_df = analyzer.check_patterns()

        # Check the LATEST completed candle (last row)
        latest = analyzed_df.iloc[-1]

        pattern_name = None

        # Priority: Engulfing > Hammer
        if latest.get("bullish_engulfing"):
            pattern_name = "BULLISH_ENGULFING"
        elif latest.get("bullish_hammer"):
            pattern_name = "BULLISH_HAMMER"

        if not pattern_name:
            return None

        # 4. Construct Signal
        # Use the date from the dataframe index (usually handles timezone info)
        # Ensure we have a date object
        signal_date = (
            latest.name.date() if hasattr(latest.name, "date") else latest.name
        )

        # Deterministic ID
        strategy_id = pattern_name  # treat pattern as strategy for now

        # Schema requires: signal_id, ds, strategy_id, symbol, pattern_name,
        # status, etc.
        param_key = f"{signal_date}|{strategy_id}|{symbol}"
        sig_id = get_deterministic_id(param_key)

        # Stop loss suggestion:
        # Common practice: For Hammer and Engulfing, place below the low.
        low_price = float(latest["low"])
        # A simple buffer, maybe 1% below low? Or just the low.
        # Let's set it to the low for now.
        suggested_stop = low_price * 0.99  # 1% buffer

        signal = Signal(
            signal_id=sig_id,
            ds=signal_date,
            strategy_id=strategy_id,
            symbol=symbol,
            pattern_name=pattern_name,
            status=SignalStatus.WAITING,
            suggested_stop=suggested_stop,
            # expiration defaults to now
        )

        return signal
