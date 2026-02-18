"""Integration tests for the Performance Pipeline with real calculations."""

from unittest.mock import MagicMock, patch

import pytest
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


def test_extract_targets_t_minus_1(pipeline):
    """Verify that extract targets T-1 data."""
    mock_bq = pipeline.bq_client

    # Mock T-1 availability check
    mock_query_check = MagicMock()
    mock_query_check.result.return_value = [MagicMock(cnt=1)]

    mock_query_extract = MagicMock()
    mock_query_extract.result.return_value = []

    # We expect two queries: one for check, one for extract
    mock_bq.query.side_effect = [mock_query_check, mock_query_extract]

    pipeline.extract()

    # Check that at least one query mentions DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    queries = [call.args[0] for call in mock_bq.query.call_args_list]
    assert any("DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)" in q for q in queries)


def test_extract_skips_if_no_data(pipeline):
    """Verify that extract returns empty list if T-1 data is not available."""
    mock_bq = pipeline.bq_client

    # Mock T-1 availability check to return 0
    mock_query_check = MagicMock()
    mock_query_check.result.return_value = [MagicMock(cnt=0)]

    mock_bq.query.return_value = mock_query_check

    results = pipeline.extract()
    assert results == []
    # Should not have called the extraction query
    assert mock_bq.query.call_count == 1
