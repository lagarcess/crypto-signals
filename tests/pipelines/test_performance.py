"""Unit tests for the Performance Pipeline."""

from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import StrategyPerformance
from crypto_signals.pipelines.performance import PerformancePipeline


@pytest.fixture
def pipeline():
    """Create a pipeline instance with mocked BigQuery client."""
    with patch("google.cloud.bigquery.Client"):
        with patch("crypto_signals.pipelines.performance.get_settings") as mock_settings:
            mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
            mock_settings.return_value.ENVIRONMENT = "DEV"
            mock_settings.return_value.SCHEMA_GUARDIAN_STRICT_MODE = True
            mock_settings.return_value.SCHEMA_MIGRATION_AUTO = True
            return PerformancePipeline()


def test_initialization(pipeline):
    """Test pipeline initialization and table IDs."""
    assert pipeline.job_name == "performance_pipeline"
    assert "stg_performance_import_test" in pipeline.staging_table_id
    assert "summary_strategy_performance_test" in pipeline.fact_table_id
    assert pipeline.schema_model == StrategyPerformance


def test_extract_generates_correct_query(pipeline):
    """Verify that extract generates the correct SQL aggregation query."""
    mock_bq = pipeline.bq_client
    mock_query_job = MagicMock()
    mock_bq.query.return_value = mock_query_job
    mock_query_job.result.return_value = []

    pipeline.extract()

    # Verify query targets the correct source table
    args, _ = mock_bq.query.call_args
    query = args[0]
    assert "FROM `test-project.crypto_analytics.agg_strategy_daily_test`" in query
    assert "GROUP BY ds, strategy_id" in query
