import pandas as pd
from crypto_signals.analysis.indicators import TechnicalIndicators
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.engine.signal_generator import SignalGenerator


def test_signal_confluence_factors():
    # Create fake data that triggers a hammer and has all confluence
    dates = pd.date_range("2024-01-01", periods=100)
    df = pd.DataFrame(
        {
            "open": [100.0] * 100,
            "high": [105.0] * 100,
            "low": [95.0] * 100,
            "close": [100.0] * 100,
            "volume": [1000.0] * 100,
        },
        index=dates,
    )

    # Trigger Hammer on last candle
    # Open 100, Close 101, High 101.5, Low 95
    # Body = 1.0, Lower Wick = 5.0 (>= 2*Body), Upper Wick = 0.5 (<= 0.5*Body)
    df.iloc[-1] = [100, 101.5, 95, 101, 3000]  # volume 3000 > 1.5*1000

    ti = TechnicalIndicators()
    ti.add_all_indicators(df)

    # Mock some values to ensure confluence passes
    df["EMA_50"] = 90.0  # Trend bullish
    df["RSI_14"] = 30.0  # Oversold / Div context
    df["ATR_SMA_20"] = 10.0  # Volatility contraction (ATR usually ~5-10)

    gen = SignalGenerator(market_provider=None)  # won't be used since we pass df
    signal = gen.generate_signals("BTC/USD", AssetClass.CRYPTO, dataframe=df)

    if signal:
        print(f"Detected Pattern: {signal.pattern_name}")
        print(f"Confluence Factors found: {signal.confluence_factors}")

        # Verify specific factors
        expected = ["volume_expansion", "volatility_contraction", "trend_bullish"]
        for fact in expected:
            if fact in signal.confluence_factors:
                print(f"✓ {fact} detected correctly")
            else:
                print(f"✗ {fact} MISSING")
    else:
        print("No signal detected.")


if __name__ == "__main__":
    test_signal_confluence_factors()
