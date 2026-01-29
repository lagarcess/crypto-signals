"""Unit tests for Strategy Synchronization Pipeline (SCD Type 2)."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.pipelines.strategy_sync import StrategySyncPipeline

# -----------------------------------------------------------------------------
# FIXTURES
# -----------------------------------------------------------------------------

@pytest.fixture
def mock_settings():
    """Mock the settings object."""
    with patch("crypto_signals.pipelines.strategy_sync.get_settings") as mock:
        mock.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
        yield mock

@pytest.fixture
def mock_firestore():
    """Mock the Firestore client."""
    with patch("google.cloud.firestore.Client") as mock:
        yield mock.return_value

@pytest.fixture
def mock_bq():
    """Mock the BigQuery client."""
    with patch("google.cloud.bigquery.Client") as mock:
        yield mock.return_value

@pytest.fixture
def pipeline(mock_settings, mock_firestore, mock_bq):
    """Create a StrategySyncPipeline instance for testing."""
    return StrategySyncPipeline()

# -----------------------------------------------------------------------------
# TESTS
# -----------------------------------------------------------------------------

def test_init(pipeline):
    """Test pipeline initialization."""
    assert pipeline.job_name == "strategy_sync"
    assert pipeline.staging_table_id == "test-project.crypto_signals.stg_strategies_import"
    assert pipeline.fact_table_id == "test-project.crypto_signals.dim_strategies"

def test_calculate_hash(pipeline):
    """Test deterministic hash calculation."""
    config1 = {
        "active": True,
        "timeframe": "4H",
        "asset_class": "CRYPTO",
        "assets": ["BTC/USD"],
        "risk_params": {"stop": 0.02},
        "extra_field": "ignore_me"
    }

    hash1 = pipeline._calculate_hash(config1)

    # Same data, different order
    config2 = {
        "risk_params": {"stop": 0.02},
        "assets": ["BTC/USD"],
        "asset_class": "CRYPTO",
        "timeframe": "4H",
        "active": True
    }
    hash2 = pipeline._calculate_hash(config2)

    assert hash1 == hash2

    # Different data
    config3 = config1.copy()
    config3["active"] = False
    hash3 = pipeline._calculate_hash(config3)

    assert hash1 != hash3

def test_extract_no_changes(pipeline, mock_bq, mock_firestore):
    """Test extract when there are no changes."""
    # Mock BQ state
    mock_row = MagicMock()
    mock_row.strategy_id = "strat_1"
    mock_row.config_hash = "correct_hash"
    mock_bq.query.return_value.result.return_value = [mock_row]

    # Mock Firestore docs
    mock_doc = MagicMock()
    mock_doc.id = "strat_1"
    mock_doc.to_dict.return_value = {
        "strategy_id": "strat_1",
        "active": True,
        "timeframe": "4H",
        "asset_class": "CRYPTO",
        "assets": ["BTC/USD"],
        "risk_params": {"stop": 0.02}
    }
    mock_firestore.collection.return_value.stream.return_value = [mock_doc]

    # Mock hash calculation to return "correct_hash"
    with patch.object(pipeline, "_calculate_hash", return_value="correct_hash"):
        result = pipeline.extract()

    assert len(result) == 0

def test_extract_new_strategy(pipeline, mock_bq, mock_firestore):
    """Test extract when a new strategy is added."""
    # Mock BQ state (empty)
    mock_bq.query.return_value.result.return_value = []

    # Mock Firestore docs
    mock_doc = MagicMock()
    mock_doc.id = "strat_new"
    mock_doc.to_dict.return_value = {
        "strategy_id": "strat_new",
        "active": True,
        "timeframe": "4H",
        "asset_class": "CRYPTO",
        "assets": ["BTC/USD"],
        "risk_params": {"stop": 0.02}
    }
    mock_firestore.collection.return_value.stream.return_value = [mock_doc]

    result = pipeline.extract()

    assert len(result) == 1
    assert result[0]["strategy_id"] == "strat_new"
    assert result[0]["is_current"] is True
    assert result[0]["valid_to"] is None

def test_extract_changed_strategy(pipeline, mock_bq, mock_firestore):
    """Test extract when a strategy has changed."""
    # Mock BQ state
    mock_row = MagicMock()
    mock_row.strategy_id = "strat_1"
    mock_row.config_hash = "old_hash"
    mock_bq.query.return_value.result.return_value = [mock_row]

    # Mock Firestore docs
    mock_doc = MagicMock()
    mock_doc.id = "strat_1"
    mock_doc.to_dict.return_value = {
        "strategy_id": "strat_1",
        "active": True,
        "timeframe": "4H",
        "asset_class": "CRYPTO",
        "assets": ["BTC/USD"],
        "risk_params": {"stop": 0.05} # Changed
    }
    mock_firestore.collection.return_value.stream.return_value = [mock_doc]

    # Check hash logic
    with patch.object(pipeline, "_calculate_hash", return_value="new_hash"):
        result = pipeline.extract()

    assert len(result) == 1
    assert result[0]["strategy_id"] == "strat_1"
    assert result[0]["config_hash"] == "new_hash"

def test_execute_merge(pipeline, mock_bq):
    """Test that custom merge executes correct queries."""
    pipeline._execute_merge()

    assert mock_bq.query.call_count == 2

    # Verify Update Query
    update_call = mock_bq.query.call_args_list[0]
    update_query = update_call[0][0]
    assert "UPDATE `test-project.crypto_signals.dim_strategies`" in update_query
    assert "SET \n                valid_to = S.valid_from,\n                is_current = FALSE" in update_query

    # Verify Insert Query
    insert_call = mock_bq.query.call_args_list[1]
    insert_query = insert_call[0][0]
    assert "INSERT INTO `test-project.crypto_signals.dim_strategies`" in insert_query
