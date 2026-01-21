from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from crypto_signals.domain.schemas import AssetClass, SignalStatus
from crypto_signals.engine.signal_generator import SignalGenerator


@pytest.fixture
def mock_market_provider():
    return MagicMock()


@pytest.fixture
def signal_generator(mock_market_provider):
    return SignalGenerator(market_provider=mock_market_provider)


def test_validate_signal_parameters_valid(signal_generator):
    """Test that valid parameters return an empty rejection list."""
    # This method doesn't exist yet, but TDD dictates we write the test first
    # We will need to expose this method or test it via a public interface if it's private.
    # For now, we assume we can access it or test via generated signals.
    pass


def test_generate_signal_with_negative_stop(signal_generator):
    """
    Test that a signal with a negative stop (due to volatility or bad math)
    returns a REJECTED_BY_FILTER signal instead of None.
    """
    # 1. Mock Data
    symbol = "BTC/USD"
    asset_class = AssetClass.CRYPTO

    # Create a dummy dataframe/series simulating a signal
    # We need to mock the pattern analyzer to return a pattern
    # Mock check_patterns to return a dataframe with a pattern
    data = {
        "close": 100.0,
        "open": 90.0,
        "high": 110.0,
        "low": 80.0,
        "volume": 1000,
        "bullish_engulfing": True,  # Trigger pattern
        "ATRr_14": 200.0,  # Huge ATR to cause negative stop
        # Stop = Low - (0.5 * ATR) = 80 - 100 = -20 (Negative Stop)
    }
    df = pd.DataFrame([data], index=[datetime.now(timezone.utc)])

    # Mock the pattern analyzer class instantiation
    with patch.object(signal_generator, "pattern_analyzer_cls") as MockAnalyzerCls:
        mock_instance = MockAnalyzerCls.return_value
        mock_instance.check_patterns.return_value = df
        mock_instance.pivots = []  # No pivots for now

        # 2. Run generate_signals
        # We need to ensure we are testing the ELLIOTT wave logic or standard logic
        # that uses ATR for stops.
        # Let's force a pattern that uses generic ATR stop logic if possible,
        # or mock the logic inside generate_signals.
        # Actually, in the current code, ELLIOTT_IMPULSE_WAVE uses ATR-based stop.
        # Or we can rely on standard logic if we modify the dataframe inject "elliott_impulse_wave": True

        df["elliott_impulse_wave"] = True
        df["bullish_engulfing"] = False

        signal = signal_generator.generate_signals(symbol, asset_class, dataframe=df)

        # 3. Assertions
        assert signal is not None, "Signal should not be None"
        assert signal.status == SignalStatus.REJECTED_BY_FILTER
        assert "VALIDATION_FAILED" in signal.rejection_reason
        assert (
            signal.suggested_stop == SignalGenerator.SAFE_STOP_VAL
        )  # Safe hydration check
