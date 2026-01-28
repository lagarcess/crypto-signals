from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from crypto_signals.domain.schemas import FactRejectedSignal, OrderSide
from crypto_signals.pipelines.rejected_signal_archival import RejectedSignalArchival


@pytest.fixture
def mock_firestore():
    return MagicMock()


@pytest.fixture
def mock_market_provider():
    return MagicMock()


@pytest.fixture
def sample_fact_rejected_signal():
    """Provides a sample FactRejectedSignal instance for testing."""
    now = datetime.now(timezone.utc)
    return FactRejectedSignal(
        doc_id="sig_1",
        signal_id="sig_1",
        created_at=now,
        ds=now.date(),
        symbol="BTC/USD",
        asset_class="CRYPTO",
        pattern_name="BULL_FLAG",
        rejection_reason="TEST",
        trade_type="FILTERED",
        side=OrderSide.BUY.value,
        entry_price=1.0,
        suggested_stop=0.9,
        take_profit_1=1.1,
        theoretical_exit_price=None,
        theoretical_exit_reason=None,
        theoretical_exit_time=None,
        theoretical_pnl_usd=0.0,
        theoretical_pnl_pct=0.0,
        theoretical_fees_usd=0.0,
    )


@pytest.fixture
def pipeline(mock_firestore, mock_market_provider):
    with (
        patch(
            "crypto_signals.pipelines.rejected_signal_archival.firestore.Client",
            return_value=mock_firestore,
        ),
        patch(
            "crypto_signals.pipelines.rejected_signal_archival.get_settings"
        ) as mock_get_settings,
        patch(
            "crypto_signals.pipelines.rejected_signal_archival.MarketDataProvider",
            return_value=mock_market_provider,
        ),
        patch(
            "crypto_signals.pipelines.rejected_signal_archival.get_stock_data_client",
            return_value=MagicMock(),
        ),
        patch(
            "crypto_signals.pipelines.rejected_signal_archival.get_crypto_data_client",
            return_value=MagicMock(),
        ),
        # Patch BigQuery client in the base class to prevent credentials error
        patch("crypto_signals.pipelines.base.bigquery.Client") as mock_bq,
        patch("crypto_signals.pipelines.base.SchemaGuardian") as mock_guardian,
    ):
        mock_get_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
        mock_get_settings.return_value.ENVIRONMENT = "PROD"
        mock_get_settings.return_value.SCHEMA_GUARDIAN_STRICT_MODE = True

        # Instantiate pipeline
        pipe = RejectedSignalArchival()
        # Inject mocks
        pipe.firestore_client = mock_firestore
        pipe.market_provider = mock_market_provider
        pipe.bq_client = mock_bq.return_value
        pipe.guardian = mock_guardian.return_value

        return pipe


def test_extract(pipeline, mock_firestore):
    """Test extracting rejected signals from Firestore."""
    mock_doc = MagicMock()
    mock_doc.id = "sig_1"
    mock_doc.to_dict.return_value = {
        "signal_id": "sig_1",
        "symbol": "BTC/USD",
        "created_at": datetime.now(timezone.utc) - timedelta(days=8),
    }

    mock_query = (
        mock_firestore.collection.return_value.where.return_value.limit.return_value
    )
    mock_query.stream.return_value = [mock_doc]

    raw_data = pipeline.extract()

    assert len(raw_data) == 1
    assert raw_data[0]["signal_id"] == "sig_1"
    assert raw_data[0]["_doc_id"] == "sig_1"


def test_transform_long_tp_hit(pipeline, mock_market_provider):
    """Test transforming a Long signal that would have hit TP1."""
    created_at = datetime.now(timezone.utc) - timedelta(days=8)
    raw_data = [
        {
            "signal_id": "sig_1",
            "symbol": "BTC/USD",
            "asset_class": "CRYPTO",
            "entry_price": 50000.0,
            "suggested_stop": 48000.0,
            "take_profit_1": 55000.0,
            "side": OrderSide.BUY.value,
            "created_at": created_at,
            "pattern_name": "BULL_FLAG",
            "rejection_reason": "TEST_REASON",
        }
    ]

    # Mock Market Data: High hits TP1
    dates = pd.date_range(created_at.date(), periods=3, freq="D", tz="UTC")
    df = pd.DataFrame(
        {
            "high": [51000.0, 56000.0, 52000.0],
            "low": [49000.0, 50000.0, 51000.0],
            "close": [50500.0, 54000.0, 52000.0],
        },
        index=dates,
    )
    mock_market_provider.get_daily_bars.return_value = df

    transformed = pipeline.transform(raw_data)

    assert len(transformed) == 1
    record = transformed[0]
    assert record["theoretical_exit_reason"] == "THEORETICAL_TP1"
    assert record["theoretical_exit_price"] == 55000.0
    assert record["theoretical_pnl_usd"] > 0


def test_transform_validation_failure(pipeline, mock_market_provider):
    """Test transforming a signal rejected due to validation failure."""
    created_at = datetime.now(timezone.utc) - timedelta(days=8)
    raw_data = [
        {
            "signal_id": "sig_val_fail",
            "symbol": "BTC/USD",
            "entry_price": 100.0,
            "suggested_stop": 90.0,
            "take_profit_1": 110.0,
            "asset_class": "CRYPTO",
            "side": OrderSide.BUY.value,
            "created_at": created_at,
            "rejection_reason": "VALIDATION_FAILED: Invalid Stop",
            "pattern_name": "TEST_PATTERN",
        }
    ]

    transformed = pipeline.transform(raw_data)

    assert len(transformed) == 1
    record = transformed[0]
    assert record["theoretical_exit_reason"] == "VALIDATION_FAILED_NO_EXECUTION"
    assert record["theoretical_pnl_usd"] == 0.0


def test_cleanup(pipeline, mock_firestore, sample_fact_rejected_signal):
    """Test cleaning up processed signals from Firestore."""
    mock_batch = mock_firestore.batch.return_value
    pipeline.cleanup([sample_fact_rejected_signal])

    assert mock_firestore.collection.called
    assert mock_batch.delete.called
    assert mock_batch.commit.called


def test_run_calls_schema_guardian(pipeline, mock_firestore, sample_fact_rejected_signal):
    """Test that the pipeline's run method calls SchemaGuardian."""
    # Mock the extract method to return some data
    pipeline.extract = MagicMock(return_value=[{"signal_id": "sig_1"}])
    transformed_data = [sample_fact_rejected_signal.model_dump(mode="json")]
    pipeline.transform = MagicMock(return_value=transformed_data)
    pipeline.cleanup = MagicMock()

    # Configure the mock to return no errors
    pipeline.bq_client.insert_rows_json.return_value = []

    # Run the pipeline
    pipeline.run()

    # Assert that SchemaGuardian.validate_schema was called
    pipeline.guardian.validate_schema.assert_called_once()
