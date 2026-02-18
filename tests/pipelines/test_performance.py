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

    # Mock T-1 availability check
    mock_query_check = MagicMock()
    mock_query_check.result.return_value = [MagicMock(cnt=1)]

    mock_query_extract = MagicMock()
    mock_query_extract.result.return_value = []

    # We expect two queries: one for check, one for extract
    mock_bq.query.side_effect = [mock_query_check, mock_query_extract]

    pipeline.extract()

    # Verify there were two queries
    assert mock_bq.query.call_count == 2

    # Verify extraction query (the second one)
    args, _ = mock_bq.query.call_args_list[1]
    query = args[0]
    assert "FROM `test-project.crypto_analytics.agg_strategy_daily_test`" in query
    assert "GROUP BY ds, strategy_id" in query
    assert "sharpe_ratio" in query
    assert "sortino_ratio" in query
    assert "max_drawdown_pct" in query
    assert "DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)" in query
