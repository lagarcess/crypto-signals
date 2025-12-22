from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from crypto_signals.pipelines.trade_archival import TradeArchivalPipeline


@pytest.fixture
def mock_alpaca():
    return MagicMock()


@pytest.fixture
def mock_firestore():
    return MagicMock()


@pytest.fixture
def mock_market_provider():
    return MagicMock()


@pytest.fixture
def pipeline(mock_alpaca, mock_firestore, mock_market_provider):
    with (
        patch(
            "crypto_signals.pipelines.trade_archival.get_trading_client",
            return_value=mock_alpaca,
        ),
        patch(
            "crypto_signals.pipelines.trade_archival.firestore.Client",
            return_value=mock_firestore,
        ),
        patch("crypto_signals.pipelines.trade_archival.settings") as mock_settings,
        patch(
            "crypto_signals.pipelines.trade_archival.MarketDataProvider",
            return_value=mock_market_provider,
        ),
    ):
        mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"

        # Instantiate pipeline
        pipe = TradeArchivalPipeline()
        # Inject mocks again to be sure (since __init__ creates them)
        pipe.alpaca = mock_alpaca
        pipe.firestore_client = mock_firestore
        pipe.market_provider = mock_market_provider

        return pipe


def test_transform_mfe_long(pipeline, mock_market_provider, mock_alpaca):
    """Test MFE calculation for a Long trade."""
    # Setup Input Data
    entry_time = datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    exit_time = datetime(2023, 1, 3, 10, 0, 0, tzinfo=timezone.utc)

    raw_position = {
        "position_id": "trade_1",
        "symbol": "BTC/USD",
        "asset_class": "CRYPTO",
        "entry_time": entry_time.isoformat(),
        "exit_time": exit_time.isoformat(),
        "exit_fill_price": 52000.0,
        "entry_fill_price": 50000.0,  # Will be overridden by Alpaca
        "qty": 1.0,
        "side": "buy",
        "account_id": "acc_1",
        "strategy_id": "strat_1",
    }

    # Mock Alpaca Order
    mock_order = MagicMock()
    mock_order.filled_avg_price = "50000.0"
    mock_order.filled_qty = "1.0"
    mock_order.side = "buy"
    mock_alpaca.get_order_by_client_order_id.return_value = mock_order

    # Mock Market Data (3 days)
    # Day 1: High 51000
    # Day 2: High 55000 (MFE trigger)
    # Day 3: High 52000
    dates = pd.date_range("2023-01-01", periods=3, freq="D", tz="UTC")
    df = pd.DataFrame(
        {
            "high": [51000.0, 55000.0, 52000.0],
            "low": [49000.0, 50000.0, 51000.0],
            "close": [50500.0, 54000.0, 52000.0],
            "open": [50000.0, 50500.0, 54000.0],
            "volume": [100.0, 200.0, 150.0],
        },
        index=dates,
    )
    mock_market_provider.get_daily_bars.return_value = df

    # Execute
    transformed = pipeline.transform([raw_position])

    # Verify
    assert len(transformed) == 1
    trade = transformed[0]
    assert trade["max_favorable_excursion"] == 5000.0  # 55000 - 50000


def test_transform_mfe_short(pipeline, mock_market_provider, mock_alpaca):
    """Test MFE calculation for a Short trade."""
    entry_time = datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    exit_time = datetime(2023, 1, 3, 10, 0, 0, tzinfo=timezone.utc)

    raw_position = {
        "position_id": "trade_2",
        "symbol": "BTC/USD",
        "asset_class": "CRYPTO",
        "entry_time": entry_time.isoformat(),
        "exit_time": exit_time.isoformat(),
        "exit_fill_price": 48000.0,
        "entry_fill_price": 50000.0,
        "qty": 1.0,
        "side": "sell",
        "account_id": "acc_1",
        "strategy_id": "strat_1",
    }

    # Mock Alpaca Order
    mock_order = MagicMock()
    mock_order.filled_avg_price = "50000.0"
    mock_order.filled_qty = "1.0"
    mock_order.side = "sell"
    mock_alpaca.get_order_by_client_order_id.return_value = mock_order

    # Mock Market Data
    # Day 1: Low 49000
    # Day 2: Low 45000 (MFE trigger)
    # Day 3: Low 48000
    dates = pd.date_range("2023-01-01", periods=3, freq="D", tz="UTC")
    df = pd.DataFrame(
        {
            "high": [51000.0, 55000.0, 52000.0],
            "low": [49000.0, 45000.0, 48000.0],
            "close": [50500.0, 46000.0, 48000.0],
            "open": [50000.0, 50500.0, 47000.0],
            "volume": [100.0, 200.0, 150.0],
        },
        index=dates,
    )
    mock_market_provider.get_daily_bars.return_value = df

    # Execute
    transformed = pipeline.transform([raw_position])

    # Verify
    assert len(transformed) == 1
    trade = transformed[0]
    assert trade["max_favorable_excursion"] == 5000.0  # 50000 - 45000
