"""
Tests for Daily Strategy Aggregation Pipeline.
"""

from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import AggStrategyDaily
from crypto_signals.pipelines.agg_strategy_daily import DailyStrategyAggregation
from google.api_core.exceptions import NotFound


@pytest.fixture
def mock_bq_client():
    # Patch where the class is imported/used
    with patch("crypto_signals.pipelines.base.bigquery.Client") as mock:
        yield mock


@pytest.fixture
def pipeline(mock_bq_client):
    # Initialize pipeline with mocked BQ client
    # We need to mock get_settings to ensure project ID is set
    with patch(
        "crypto_signals.pipelines.agg_strategy_daily.get_settings"
    ) as mock_settings:
        mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
        mock_settings.return_value.ENVIRONMENT = "TEST"
        # Also patch base settings used in __init__
        with patch(
            "crypto_signals.pipelines.base.get_settings",
            return_value=mock_settings.return_value,
        ):
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
            "trade_count": 10,
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


def test_run_flow(pipeline):
    """Test full pipeline execution flow (mocked)."""
    # Mock internal methods to isolate logic
    pipeline.guardian = MagicMock()  # Mock guardian to pass validation

    # Mock extract
    pipeline.extract = MagicMock(
        return_value=[
            {
                "ds": "2023-01-01",
                "agg_id": "2023-01-01|strat1|BTC/USD",
                "strategy_id": "strat1",
                "symbol": "BTC/USD",
                "total_pnl": 100.0,
                "win_rate": 0.6,
                "trade_count": 10,
            }
        ]
    )

    # Mock base class methods
    # We mock the methods called by run() to verify orchestration
    pipeline._truncate_staging = MagicMock()
    pipeline._load_to_staging = MagicMock()
    pipeline._execute_merge = MagicMock()

    # Execute
    processed_count = pipeline.run()

    # Verify flow
    assert processed_count == 1

    # Check base flow
    # Now called twice (fact and staging) via BigQueryPipelineBase.run()
    assert pipeline.guardian.validate_schema.call_count == 2
    pipeline.extract.assert_called_once()
    pipeline._truncate_staging.assert_called_once()
    pipeline._load_to_staging.assert_called_once()
    pipeline._execute_merge.assert_called_once()


def test_run_with_auto_creation(pipeline):
    """Test that run() triggers migrate_schema (creation) if tables are missing."""
    # Ensure auto-migration is enabled
    pipeline.settings.SCHEMA_MIGRATION_AUTO = True
    # Mock guardian
    pipeline.guardian = MagicMock()
    # Setup: validate_schema raises NotFound on first call, success on second
    # (to simulate table creation then successful re-validation)
    pipeline.guardian.validate_schema.side_effect = [
        NotFound("Table not found"),  # Fact Table Validation 1
        None,  # Fact Table Re-validation
        NotFound("Table not found"),  # Staging Table Validation
    ]

    # Mock extract to return empty to stop after pre-flight
    pipeline.extract = MagicMock(return_value=[])

    # We expect it to continue until it hits some other missing mock or finishes
    try:
        pipeline.run()
    except Exception:
        pass

    # Check that migrate_schema was called for both fact and staging
    # And verify it passed the correct partition_column="ds"
    assert pipeline.guardian.migrate_schema.call_count == 2

    # Verify first call (fact table)
    args, kwargs = pipeline.guardian.migrate_schema.call_args_list[0]
    assert args[0] == pipeline.fact_table_id
    assert kwargs["partition_column"] == "ds"

    # Verify second call (staging table)
    args, kwargs = pipeline.guardian.migrate_schema.call_args_list[1]
    assert args[0] == pipeline.staging_table_id
    assert kwargs["partition_column"] == "ds"
