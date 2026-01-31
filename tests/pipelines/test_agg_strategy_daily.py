"""
Tests for Daily Strategy Aggregation Pipeline.
"""

from unittest.mock import MagicMock, patch

import pytest
from google.cloud import bigquery

from crypto_signals.domain.schemas import AggStrategyDaily
from crypto_signals.pipelines.agg_strategy_daily import DailyStrategyAggregation


@pytest.fixture
def mock_bq_client():
    # Patch where the class is imported/used
    with patch("crypto_signals.pipelines.base.bigquery.Client") as mock:
        yield mock


@pytest.fixture
def pipeline(mock_bq_client):
    # Initialize pipeline with mocked BQ client
    # We need to mock get_settings to ensure project ID is set
    with patch("crypto_signals.pipelines.agg_strategy_daily.get_settings") as mock_settings:
        mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
        mock_settings.return_value.ENVIRONMENT = "TEST"
        # Also patch base settings used in __init__
        with patch("crypto_signals.pipelines.base.get_settings", return_value=mock_settings.return_value):
             return DailyStrategyAggregation()


def test_initialization(pipeline):
    """Test that pipeline is initialized with correct settings."""
    assert pipeline.job_name == "agg_strategy_daily"
    assert "agg_strategy_daily" in pipeline.fact_table_id
    assert "stg_agg_strategy_daily" in pipeline.staging_table_id
    assert pipeline.id_column == "agg_id"
    assert pipeline.partition_column == "ds"
    assert pipeline.schema_model == AggStrategyDaily


def test_extract_generates_correct_query(pipeline):
    """Test that extract method generates valid SQL."""
    # Mock query result
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [
        {
            "ds": "2023-01-01",
            "agg_id": "2023-01-01|strat1|BTC/USD",
            "strategy_id": "strat1",
            "symbol": "BTC/USD",
            "total_pnl": 100.0,
            "win_rate": 0.6,
            "trade_count": 10
        }
    ]
    pipeline.bq_client.query.return_value = mock_query_job

    data = pipeline.extract()

    assert len(data) == 1
    assert data[0]["agg_id"] == "2023-01-01|strat1|BTC/USD"

    # Verify SQL
    args, _ = pipeline.bq_client.query.call_args
    query = args[0]
    assert "SELECT" in query
    assert "FROM" in query
    assert "GROUP BY ds, strategy_id, symbol" in query
    assert "agg_id" in query
    assert "win_rate" in query


def test_create_table_if_not_exists(pipeline):
    """Test table creation logic."""
    # Scenario 1: Table exists
    pipeline.bq_client.get_table.return_value = MagicMock()
    pipeline._create_table_if_not_exists("test_table")
    pipeline.bq_client.create_table.assert_not_called()

    # Scenario 2: Table not found (Exception raised by get_table)
    pipeline.bq_client.get_table.side_effect = Exception("Not Found")
    pipeline._create_table_if_not_exists("project.dataset.test_table")

    # Verify create_table called
    pipeline.bq_client.create_table.assert_called_once()
    args, _ = pipeline.bq_client.create_table.call_args
    table_arg = args[0]
    assert isinstance(table_arg, bigquery.Table)
    # bigquery.Table parses the full ID
    assert table_arg.table_id == "test_table"
    assert table_arg.dataset_id == "dataset"
    assert table_arg.project == "project"
    assert len(table_arg.schema) > 0


def test_run_flow(pipeline):
    """Test full pipeline execution flow (mocked)."""
    # Mock internal methods to isolate logic
    pipeline._create_table_if_not_exists = MagicMock()
    pipeline.guardian = MagicMock() # Mock guardian to pass validation

    # Mock extract
    pipeline.extract = MagicMock(return_value=[
         {
            "ds": "2023-01-01",
            "agg_id": "2023-01-01|strat1|BTC/USD",
            "strategy_id": "strat1",
            "symbol": "BTC/USD",
            "total_pnl": 100.0,
            "win_rate": 0.6,
            "trade_count": 10
        }
    ])

    # Mock base class methods
    # We mock the methods called by run() to verify orchestration
    pipeline._truncate_staging = MagicMock()
    pipeline._load_to_staging = MagicMock()
    pipeline._execute_merge = MagicMock()

    # Execute
    processed_count = pipeline.run()

    # Verify flow
    assert processed_count == 1
    # Check table creation hooks
    assert pipeline._create_table_if_not_exists.call_count == 2 # Fact and Staging

    # Check base flow
    pipeline.guardian.validate_schema.assert_called_once()
    pipeline.extract.assert_called_once()
    pipeline._truncate_staging.assert_called_once()
    pipeline._load_to_staging.assert_called_once()
    pipeline._execute_merge.assert_called_once()
