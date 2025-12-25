"""Unit tests for Firestore SignalRepository and PositionRepository."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import (
    AssetClass,
    OrderSide,
    Position,
    Signal,
    SignalStatus,
    TradeStatus,
)
from crypto_signals.repository.firestore import PositionRepository, SignalRepository


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
    assert repo.collection_name == "live_signals"


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
        asset_class=AssetClass.CRYPTO,
        entry_price=48000.0,
        pattern_name="bullish_engulfing",
        status=SignalStatus.WAITING,
        suggested_stop=45000.0,
        expiration_at=datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
    )

    # Execute
    repo.save(signal)

    # Verify interactions
    mock_db.collection.assert_called_once_with("live_signals")
    mock_collection.document.assert_called_once_with("test-signal-id")

    # Verify data passed to set()
    # model_dump(mode="json") converts dates/datetimes to ISO strings
    expected_data = signal.model_dump(mode="json")
    # Verify data passed to set() manually to handle expireAt
    mock_document.set.assert_called_once()
    args, _ = mock_document.set.call_args
    actual_data = args[0]

    # Check expireAt exists then remove it for equality check
    assert "expireAt" in actual_data
    del actual_data["expireAt"]

    expected_data = signal.model_dump(mode="json")
    assert actual_data == expected_data


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
        asset_class=AssetClass.CRYPTO,
        entry_price=105.0,
        pattern_name="pattern",
        status=SignalStatus.WAITING,
        suggested_stop=100.0,
    )

    # Verify exception is raised and not swallowed
    with pytest.raises(RuntimeError, match="Firestore connection failed"):
        repo.save(signal)


# =============================================================================
# SignalRepository.get_by_id Tests
# =============================================================================


class TestSignalRepositoryGetById:
    """Tests for SignalRepository.get_by_id method."""

    def test_get_by_id_found(self, mock_settings, mock_firestore_client):
        """Test get_by_id returns Signal when found."""
        from unittest.mock import MagicMock

        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_doc_ref = mock_collection.document.return_value
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "signal_id": "test-signal-123",
            "ds": "2025-01-15",
            "strategy_id": "test-strategy",
            "symbol": "BTC/USD",
            "asset_class": "CRYPTO",
            "entry_price": 50000.0,
            "pattern_name": "bullish_engulfing",
            "status": "WAITING",
            "suggested_stop": 48000.0,
        }
        mock_doc_ref.get.return_value = mock_doc

        repo = SignalRepository()
        result = repo.get_by_id("test-signal-123")

        assert result is not None
        assert result.signal_id == "test-signal-123"
        assert result.symbol == "BTC/USD"
        mock_collection.document.assert_called_with("test-signal-123")

    def test_get_by_id_not_found(self, mock_settings, mock_firestore_client):
        """Test get_by_id returns None when not found."""
        from unittest.mock import MagicMock

        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_doc_ref = mock_collection.document.return_value
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_doc_ref.get.return_value = mock_doc

        repo = SignalRepository()
        result = repo.get_by_id("nonexistent-signal")

        assert result is None
        mock_collection.document.assert_called_with("nonexistent-signal")


# =============================================================================
# SignalRepository.update_signal_atomic Tests
# =============================================================================


class TestSignalRepositoryAtomicUpdate:
    """Tests for SignalRepository.update_signal_atomic transactional method."""

    def test_atomic_update_success(self, mock_settings, mock_firestore_client):
        """Test successful atomic update returns True."""
        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_doc_ref = mock_collection.document.return_value

        # Mock the transaction
        mock_transaction = MagicMock()
        mock_db.transaction.return_value = mock_transaction

        # Mock snapshot exists
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        mock_doc_ref.get.return_value = mock_snapshot

        repo = SignalRepository()

        # Execute with actual firestore.transactional decorator behavior
        with patch("google.cloud.firestore.transactional") as mock_transactional:
            # Make transactional decorator pass through and call the function
            mock_transactional.side_effect = lambda fn: fn

            result = repo.update_signal_atomic("test-signal-123", {"status": "TP1_HIT"})

        assert result is True
        mock_collection.document.assert_called_with("test-signal-123")
        mock_transaction.update.assert_called_once_with(
            mock_doc_ref, {"status": "TP1_HIT"}
        )

    def test_atomic_update_nonexistent_document(
        self, mock_settings, mock_firestore_client
    ):
        """Test atomic update returns False for non-existent document."""
        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_doc_ref = mock_collection.document.return_value

        # Mock the transaction
        mock_transaction = MagicMock()
        mock_db.transaction.return_value = mock_transaction

        # Mock snapshot does NOT exist
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        mock_doc_ref.get.return_value = mock_snapshot

        repo = SignalRepository()

        with patch("google.cloud.firestore.transactional") as mock_transactional:
            mock_transactional.side_effect = lambda fn: fn

            result = repo.update_signal_atomic(
                "nonexistent-signal", {"status": "TP1_HIT"}
            )

        assert result is False
        mock_collection.document.assert_called_with("nonexistent-signal")
        # update should NOT have been called
        mock_transaction.update.assert_not_called()

    def test_atomic_update_transaction_failure(
        self, mock_settings, mock_firestore_client
    ):
        """Test atomic update returns False when transaction fails."""
        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        # Note: mock_doc_ref not needed as transaction fails before document access
        _ = mock_collection.document.return_value

        # Mock the transaction to raise an exception
        mock_db.transaction.side_effect = Exception(
            "Transaction conflict: retries exhausted"
        )

        repo = SignalRepository()

        with patch("google.cloud.firestore.transactional") as mock_transactional:
            mock_transactional.side_effect = lambda fn: fn

            result = repo.update_signal_atomic("test-signal-123", {"status": "TP1_HIT"})

        # Should gracefully return False, not raise
        assert result is False
        mock_collection.document.assert_called_with("test-signal-123")


@pytest.fixture
def sample_position():
    """Create a sample position for testing."""
    return Position(
        position_id="test-position-123",
        ds=date(2025, 1, 15),
        account_id="alpaca-order-456",
        symbol="BTC/USD",
        signal_id="test-signal-123",
        status=TradeStatus.OPEN,
        entry_fill_price=50000.0,
        current_stop_loss=48000.0,
        qty=0.05,
        side=OrderSide.BUY,
    )


class TestPositionRepositoryInit:
    """Tests for PositionRepository initialization."""

    def test_init(self, mock_settings, mock_firestore_client):
        """Test repository initialization."""
        repo = PositionRepository()

        mock_firestore_client.assert_called_with(project="test-project")
        assert repo.collection_name == "live_positions"


class TestPositionRepositorySave:
    """Tests for PositionRepository.save method."""

    def test_save_new_position(
        self, mock_settings, mock_firestore_client, sample_position
    ):
        """Test saving a new position sets created_at."""
        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_doc_ref = mock_collection.document.return_value
        mock_doc_ref.get.return_value.exists = False  # New document

        repo = PositionRepository()
        repo.save(sample_position)

        # Verify collection and document access
        mock_db.collection.assert_called_with("live_positions")
        mock_collection.document.assert_called_with("test-position-123")

        # Verify set was called with merge=True
        mock_doc_ref.set.assert_called_once()
        call_args, call_kwargs = mock_doc_ref.set.call_args
        assert call_kwargs.get("merge") is True

        # Verify created_at was set (not updated_at for new docs)
        saved_data = call_args[0]
        assert "created_at" in saved_data

    def test_save_existing_position_preserves_created_at(
        self, mock_settings, mock_firestore_client, sample_position
    ):
        """Test saving existing position sets updated_at, not created_at."""
        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_doc_ref = mock_collection.document.return_value
        mock_doc_ref.get.return_value.exists = True  # Existing document

        repo = PositionRepository()
        repo.save(sample_position)

        # Verify set was called with merge=True
        call_args, call_kwargs = mock_doc_ref.set.call_args
        saved_data = call_args[0]

        # Should have updated_at, not created_at
        assert "updated_at" in saved_data
        assert "created_at" not in saved_data


class TestPositionRepositoryGetOpenPositions:
    """Tests for PositionRepository.get_open_positions method."""

    def test_get_open_positions_returns_list(self, mock_settings, mock_firestore_client):
        """Test getting open positions returns Position objects."""
        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_query = mock_collection.where.return_value

        # Simulate empty result
        mock_query.stream.return_value = []

        repo = PositionRepository()
        positions = repo.get_open_positions()

        assert positions == []
        mock_collection.where.assert_called_once()


class TestPositionRepositoryGetBySignal:
    """Tests for PositionRepository.get_position_by_signal method."""

    def test_get_position_by_signal_not_found(self, mock_settings, mock_firestore_client):
        """Test returns None when no position found."""
        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_query = mock_collection.where.return_value.limit.return_value

        # Simulate no results
        mock_query.stream.return_value = []

        repo = PositionRepository()
        result = repo.get_position_by_signal("nonexistent-signal")

        assert result is None


class TestPositionRepositoryUpdate:
    """Tests for PositionRepository.update_position method."""

    def test_update_position(self, mock_settings, mock_firestore_client, sample_position):
        """Test updating a position."""
        mock_db = mock_firestore_client.return_value
        mock_collection = mock_db.collection.return_value
        mock_doc_ref = mock_collection.document.return_value

        repo = PositionRepository()
        repo.update_position(sample_position)

        # Verify document access
        mock_collection.document.assert_called_with("test-position-123")

        # Verify set was called with merge=True
        mock_doc_ref.set.assert_called_once()
        call_args, call_kwargs = mock_doc_ref.set.call_args
        assert call_kwargs.get("merge") is True

        # Verify updated_at was set
        saved_data = call_args[0]
        assert "updated_at" in saved_data
