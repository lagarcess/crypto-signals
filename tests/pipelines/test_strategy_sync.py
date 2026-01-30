"""Unit tests for Strategy Synchronization Pipeline (SCD Type 2)."""

from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import StrategyConfig
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
def mock_repo():
    """Mock the StrategyRepository."""
    with patch("crypto_signals.pipelines.strategy_sync.StrategyRepository") as mock_class:
        mock_instance = mock_class.return_value
        yield mock_instance


@pytest.fixture
def mock_bq():
    """Mock the BigQuery client."""
    with patch("google.cloud.bigquery.Client") as mock:
        yield mock.return_value


@pytest.fixture
def pipeline(mock_settings, mock_repo, mock_bq):
    """Create a StrategySyncPipeline instance for testing."""
    p = StrategySyncPipeline()
    p.repository = mock_repo  # Ensure the instance uses the mock
    return p


# -----------------------------------------------------------------------------
# TESTS
# -----------------------------------------------------------------------------


def test_init(pipeline):
    """Test pipeline initialization."""
    assert pipeline.job_name == "strategy_sync"
    assert (
        pipeline.staging_table_id == "test-project.crypto_signals.stg_strategies_import"
    )
    assert pipeline.fact_table_id == "test-project.crypto_signals.dim_strategies"


def test_calculate_hash(pipeline):
    """Test deterministic hash calculation."""
    config1 = {
        "active": True,
        "timeframe": "4H",
        "asset_class": "CRYPTO",
        "assets": ["BTC/USD"],
        "risk_params": {"stop": 0.02},
        "extra_field": "ignore_me",
    }

    hash1 = pipeline._calculate_hash(config1)

    # Same data, different order
    config2 = {
        "risk_params": {"stop": 0.02},
        "assets": ["BTC/USD"],
        "asset_class": "CRYPTO",
        "timeframe": "4H",
        "active": True,
    }
    hash2 = pipeline._calculate_hash(config2)

    assert hash1 == hash2

    # Different data
    config3 = config1.copy()
    config3["active"] = False
    hash3 = pipeline._calculate_hash(config3)

    assert hash1 != hash3


def test_extract_no_changes(pipeline, mock_bq, mock_repo):
    """Test extract when there are no changes."""
    # Mock BQ state
    mock_row = MagicMock()
    mock_row.strategy_id = "strat_1"
    mock_row.config_hash = "correct_hash"
    mock_bq.query.return_value.result.return_value = [mock_row]

    # Mock Repository return
    strat_1 = StrategyConfig(
        strategy_id="strat_1",
        active=True,
        timeframe="4H",
        asset_class="CRYPTO",
        assets=["BTC/USD"],
        risk_params={"stop": 0.02},
    )
    mock_repo.get_all_strategies.return_value = [strat_1]

    # Mock hash calculation to return "correct_hash"
    with patch.object(pipeline, "_calculate_hash", return_value="correct_hash"):
        result = pipeline.extract()

    assert len(result) == 0


def test_extract_new_strategy(pipeline, mock_bq, mock_repo):
    """Test extract when a new strategy is added."""
    # Mock BQ state (empty)
    mock_bq.query.return_value.result.return_value = []

    # Mock Repository return
    strat_new = StrategyConfig(
        strategy_id="strat_new",
        active=True,
        timeframe="4H",
        asset_class="CRYPTO",
        assets=["BTC/USD"],
        risk_params={"stop": 0.02},
    )
    mock_repo.get_all_strategies.return_value = [strat_new]

    result = pipeline.extract()

    assert len(result) == 1
    assert result[0]["strategy_id"] == "strat_new"
    assert result[0]["is_current"] is True
    assert result[0]["valid_to"] is None


def test_extract_changed_strategy(pipeline, mock_bq, mock_repo):
    """Test extract when a strategy has changed."""
    # Mock BQ state
    mock_row = MagicMock()
    mock_row.strategy_id = "strat_1"
    mock_row.config_hash = "old_hash"
    mock_bq.query.return_value.result.return_value = [mock_row]

    # Mock Repository return
    strat_1 = StrategyConfig(
        strategy_id="strat_1",
        active=True,
        timeframe="4H",
        asset_class="CRYPTO",
        assets=["BTC/USD"],
        risk_params={"stop": 0.05},  # Changed
    )
    mock_repo.get_all_strategies.return_value = [strat_1]

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
    normalized_update = " ".join(update_query.split())

    assert "UPDATE `test-project.crypto_signals.dim_strategies`" in update_query
    assert "SET valid_to = S.valid_from, is_current = FALSE" in normalized_update

    # Verify Insert Query
    insert_call = mock_bq.query.call_args_list[1]
    insert_query = insert_call[0][0]
    assert "INSERT INTO `test-project.crypto_signals.dim_strategies`" in insert_query
