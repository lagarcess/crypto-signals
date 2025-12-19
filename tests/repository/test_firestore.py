"""Unit tests for Firestore SignalRepository."""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from crypto_signals.domain.schemas import Signal, SignalStatus
from crypto_signals.repository.firestore import SignalRepository


@pytest.fixture
def mock_settings():
    """Mock application settings."""
    with patch("crypto_signals.repository.firestore.get_settings") as mock:
        mock.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
        yield mock


@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client."""
    with patch("google.cloud.firestore.Client") as mock:
        yield mock


def test_init(mock_settings, mock_firestore_client):
    """Test repository initialization."""
    repo = SignalRepository()

    mock_settings.assert_called_once()
    mock_firestore_client.assert_called_once_with(project="test-project")
    assert repo.collection_name == "generated_signals"


def test_save_signal(mock_settings, mock_firestore_client):
    """Test saving a signal to Firestore."""
    # Setup mocks
    mock_db = mock_firestore_client.return_value
    mock_collection = mock_db.collection.return_value
    mock_document = mock_collection.document.return_value

    repo = SignalRepository()

    # Create test signal
    signal = Signal(
        signal_id="test-signal-id",
        ds=date(2025, 1, 1),
        strategy_id="test-strategy",
        symbol="BTC/USD",
        pattern_name="bullish_engulfing",
        status=SignalStatus.WAITING,
        suggested_stop=45000.0,
        expiration_at=datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
    )

    # Execute
    repo.save(signal)

    # Verify interactions
    mock_db.collection.assert_called_once_with("generated_signals")
    mock_collection.document.assert_called_once_with("test-signal-id")

    # Verify data passed to set()
    # model_dump(mode="json") converts dates/datetimes to ISO strings
    expected_data = signal.model_dump(mode="json")
    mock_document.set.assert_called_once_with(expected_data)


def test_save_signal_firestore_error(mock_settings, mock_firestore_client):
    """Test that Firestore errors are propagated."""
    # Setup mocks
    mock_db = mock_firestore_client.return_value
    mock_collection = mock_db.collection.return_value
    mock_document = mock_collection.document.return_value

    # Simulate Firestore error
    mock_document.set.side_effect = RuntimeError("Firestore connection failed")

    repo = SignalRepository()

    # Create dummy signal
    signal = Signal(
        signal_id="test-error",
        ds=date(2025, 1, 1),
        strategy_id="strat",
        symbol="BTC/USD",
        pattern_name="pattern",
        status=SignalStatus.WAITING,
        suggested_stop=100.0,
    )

    # Verify exception is raised and not swallowed
    with pytest.raises(RuntimeError, match="Firestore connection failed"):
        repo.save(signal)
