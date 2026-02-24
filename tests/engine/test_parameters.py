"""
Unit tests for the SignalParameterFactory.
"""

from datetime import timedelta, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest
from crypto_signals.domain.schemas import AssetClass
from crypto_signals.engine.parameters import SignalParameterFactory


@pytest.fixture
def factory():
    return SignalParameterFactory()


@pytest.fixture
def mock_analyzer():
    analyzer = MagicMock()
    analyzer.pivots = []
    return analyzer


def test_bull_flag_parameters(factory, mock_analyzer):
    """Test parameter calculation for Bull Flag."""
    latest = pd.Series(
        {
            "close": 100.0,
            "low": 90.0,
            "high": 110.0,
            "open": 95.0,
            "ATRr_14": 5.0,
            "bull_flag_duration": 10,
            "bull_flag_classification": "STANDARD",
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="BULL_FLAG",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
    )

    # Expected calculations:
    # pole_high = 110.0, pole_low = 90.0
    # atr = 5.0
    # flagpole_height = max(5.0 * 3.0, 110-90) = max(15, 20) = 20.0
    # tp1 = 100 + 0.5 * 20 = 110
    # tp2 = 100 + 1.0 * 20 = 120
    # tp3 = 100 + 1.5 * 20 = 130
    # stop = 90 * 0.99 = 89.1

    assert params["symbol"] == "BTC/USD"
    assert params["pattern_name"] == "BULL_FLAG"
    assert params["take_profit_1"] == 110.0
    assert params["take_profit_2"] == 120.0
    assert params["take_profit_3"] == 130.0
    assert params["suggested_stop"] == 89.1
    assert params["pattern_duration_days"] == 10
    assert params["pattern_classification"] == "STANDARD"


def test_elliott_wave_micro_cap_safety(factory, mock_analyzer):
    """Test Elliott Wave with micro-cap safety (Issue #136)."""
    # Low price and high volatility causing potential negative stop
    latest = pd.Series(
        {
            "close": 0.00000080,
            "low": 0.00000080,
            "high": 0.00000090,
            "open": 0.00000085,
            "ATRr_14": 0.00000200,
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="PEPE/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="ELLIOTT_IMPULSE_WAVE",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
    )

    # Calculation:
    # stop = low - (0.5 * atr) = 0.8e-6 - 1.0e-6 = -0.2e-6
    # Should be capped at SAFE_STOP_VAL = 1e-8

    assert params["suggested_stop"] == factory.SAFE_STOP_VAL
    assert params["suggested_stop"] > 0


def test_elliott_wave_normal(factory, mock_analyzer):
    """Test Elliott Wave normal calculation."""
    latest = pd.Series(
        {
            "close": 100.0,
            "low": 90.0,
            "high": 110.0,
            "open": 95.0,
            "ATRr_14": 5.0,
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="ELLIOTT_IMPULSE_WAVE",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
    )

    # stop = 90 - 2.5 = 87.5
    assert params["suggested_stop"] == 87.5


def test_bullish_hammer(factory, mock_analyzer):
    """Test Bullish Hammer parameters."""
    latest = pd.Series(
        {
            "close": 100.0,
            "low": 90.0,
            "high": 110.0,
            "open": 95.0,
            "ATRr_14": 5.0,
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="BULLISH_HAMMER",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
    )

    # invalidation = low = 90
    # stop = 90 * 0.99 = 89.1
    # TPs (default ATR based):
    # tp1 = 100 + 2*5 = 110

    assert params["invalidation_price"] == 90.0
    assert params["suggested_stop"] == 89.1
    assert params["take_profit_1"] == 110.0


def test_hydrate_safe_values(factory):
    """Test safe hydration logic."""
    bad_params = {
        "suggested_stop": -1.0,
        "take_profit_1": 0.0,
        "take_profit_2": -5.0,
        "take_profit_3": None,
    }

    safe = factory.hydrate_safe_values(bad_params)

    assert safe["suggested_stop"] == factory.SAFE_STOP_VAL
    assert safe["take_profit_1"] == factory.SAFE_TP1_VAL
    assert safe["take_profit_2"] == factory.SAFE_TP2_VAL
    assert safe["take_profit_3"] == factory.SAFE_TP3_VAL


def test_confluence_factors(factory, mock_analyzer):
    """Test extraction of confluence factors."""
    latest = pd.Series(
        {
            "close": 100.0,
            "low": 90.0,
            "open": 95.0,
            "rsi_bullish_divergence": True,
            "volume_expansion": True,
            "trend_bullish": False,
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="TEST_PATTERN",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
        geometric_pattern_name="BULL_FLAG",
    )

    assert "rsi_bullish_divergence" in params["confluence_factors"]
    assert "volume_expansion" in params["confluence_factors"]
    assert "trend_bullish" not in params["confluence_factors"]
    # If harmonic_pattern is provided, geometric_pattern_name is appended,
    # but here harmonic_pattern is None, so check logic again.
    assert "BULL_FLAG" not in params["confluence_factors"]


def test_harmonic_metadata(factory, mock_analyzer):
    """Test harmonic metadata extraction."""
    latest = pd.Series({"close": 100.0, "low": 90.0, "open": 95.0})
    latest.name = pd.Timestamp("2023-01-01")

    mock_harmonic = MagicMock()
    mock_harmonic.ratios = {"XA": 0.618}
    mock_harmonic.is_macro = True
    mock_harmonic.pattern_type = "GARTLEY"

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="GARTLEY",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
        harmonic_pattern=mock_harmonic,
    )

    assert (
        params["strategy_id"] == "GARTLEY"
    )  # Multi-Layer: strategy stays as pattern_name
    assert params["pattern_classification"] == "MACRO_PATTERN"
    assert params["harmonic_metadata"] == {"XA": 0.618}
    assert params["structural_context"] == "GARTLEY"  # Harmonic type stored as context
    assert params["conviction_tier"] == "HIGH"  # Tactical + structural

    expected_ts = pd.Timestamp("2023-01-01").to_pydatetime().replace(
        tzinfo=timezone.utc
    ) + timedelta(hours=120)
    assert params["valid_until"] == expected_ts


def test_morning_star(factory, mock_analyzer):
    """Test Morning Star parameters."""
    latest = pd.Series(
        {
            "close": 100.0,
            "low": 90.0,
            "high": 110.0,
            "open": 95.0,
            "ATRr_14": 5.0,
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="MORNING_STAR",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
    )

    # invalidation = low = 90
    # stop = 90 * 0.99 = 89.1
    # TPs (default ATR based)
    assert params["invalidation_price"] == 90.0
    assert params["suggested_stop"] == 89.1


def test_bullish_engulfing(factory, mock_analyzer):
    """Test Bullish Engulfing parameters."""
    latest = pd.Series(
        {
            "close": 105.0,
            "low": 90.0,
            "high": 110.0,
            "open": 95.0,
            "ATRr_14": 5.0,
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="BULLISH_ENGULFING",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
    )

    # invalidation = open = 95.0
    # stop = 95.0 * 0.99 = 94.05
    assert params["invalidation_price"] == 95.0
    assert params["suggested_stop"] == 94.05


def test_bullish_marubozu(factory, mock_analyzer):
    """Test Bullish Marubozu parameters."""
    latest = pd.Series(
        {
            "close": 110.0,
            "low": 90.0,
            "high": 110.0,
            "open": 90.0,
            "ATRr_14": 5.0,
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="BULLISH_MARUBOZU",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
    )

    # midpoint = (90+110)/2 = 100
    # invalidation = 100
    # stop = 100 * 0.99 = 99.0
    assert params["invalidation_price"] == 100.0
    assert params["suggested_stop"] == 99.0


def test_fallthrough_pattern(factory, mock_analyzer):
    """Test standard fallback logic for generic patterns."""
    latest = pd.Series(
        {
            "close": 100.0,
            "low": 90.0,
            "high": 110.0,
            "open": 95.0,
            "ATRr_14": 5.0,
        }
    )
    latest.name = pd.Timestamp("2023-01-01")

    params = factory.get_parameters(
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        pattern_name="INVERSE_HEAD_SHOULDERS",
        latest=latest,
        sig_id="test_id",
        analyzer=mock_analyzer,
    )

    # Default stop: low * 0.99 = 89.1
    # Default TP1: close + 2*ATR = 100 + 10 = 110
    assert params["suggested_stop"] == 89.1
    assert params["take_profit_1"] == 110.0
    assert params["invalidation_price"] is None
