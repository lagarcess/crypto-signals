from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import StrategyConfig
from crypto_signals.repository.firestore import StrategyRepository


@pytest.fixture
def mock_firestore():
    with patch("google.cloud.firestore.Client") as mock:
        yield mock.return_value


@pytest.fixture
def repo(mock_firestore):
    return StrategyRepository()


def test_get_all_strategies(repo, mock_firestore):
    # Mock documents
    doc1 = MagicMock()
    doc1.id = "strat_1"
    doc1.to_dict.return_value = {
        "strategy_id": "strat_1",
        "active": True,
        "timeframe": "4H",
        "asset_class": "CRYPTO",
        "assets": ["BTC/USD"],
        "risk_params": {"stop": 0.02},
    }

    mock_firestore.collection.return_value.stream.return_value = [doc1]

    results = repo.get_all_strategies()

    assert len(results) == 1
    assert isinstance(results[0], StrategyConfig)
    assert results[0].strategy_id == "strat_1"


def test_get_all_strategies_validation_error(repo, mock_firestore):
    # Mock valid and invalid documents
    doc1 = MagicMock()
    doc1.id = "valid"
    doc1.to_dict.return_value = {
        "strategy_id": "valid",
        "active": True,
        "timeframe": "4H",
        "asset_class": "CRYPTO",
        "assets": ["BTC/USD"],
    }

    doc2 = MagicMock()
    doc2.id = "invalid"
    doc2.to_dict.return_value = {
        "active": True  # Missing required fields
    }

    mock_firestore.collection.return_value.stream.return_value = [doc1, doc2]

    results = repo.get_all_strategies()

    assert len(results) == 1
    assert results[0].strategy_id == "valid"


def test_save_does_not_mutate_input(repo, mock_firestore):
    """Verify that save() does not mutate the input object and sets updated_at."""
    strategy = StrategyConfig(
        strategy_id="strat_test",
        active=True,
        timeframe="1D",
        asset_class="CRYPTO",
        assets=["BTC/USD"],
        risk_params={"stop_loss_pct": 0.02},
    )

    # Initial state
    assert strategy.updated_at is None

    # Call save
    repo.save(strategy)

    # Verify input object IS NOT mutated
    assert strategy.updated_at is None

    # Verify Firestore Client received data WITH updated_at
    mock_coll = mock_firestore.collection.return_value
    mock_doc = mock_coll.document.return_value
    mock_doc.set.assert_called_once()

    args, _ = mock_doc.set.call_args
    data = args[0]
    assert "updated_at" in data
    assert data["updated_at"] is not None


def test_get_modified_strategies(repo, mock_firestore):
    """Verify get_modified_strategies calls Firestore with correct filter."""
    from datetime import datetime, timezone

    since = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # Mock documents
    doc1 = MagicMock()
    doc1.id = "strat_modified"
    doc1.to_dict.return_value = {
        "strategy_id": "strat_modified",
        "active": True,
        "timeframe": "4H",
        "asset_class": "CRYPTO",
        "assets": ["BTC/USD"],
        "updated_at": datetime.now(timezone.utc),
    }

    mock_coll = mock_firestore.collection.return_value
    mock_query = mock_coll.where.return_value
    mock_query.stream.return_value = [doc1]

    results = repo.get_modified_strategies(since=since)

    # Verify Firestore query filter
    mock_coll.where.assert_called_once()
    _, kwargs = mock_coll.where.call_args
    # FieldFilter is used in the repository
    assert kwargs["filter"].field_path == "updated_at"
    assert kwargs["filter"].op_string == ">"
    assert kwargs["filter"].value == since

    assert len(results) == 1
    assert results[0].strategy_id == "strat_modified"
