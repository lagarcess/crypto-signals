"""Unit tests for the Performance Pipeline."""

from unittest.mock import MagicMock

import pytest
from crypto_signals.domain.schemas import StrategyPerformance


class TestPerformancePipelineInit:
    """Tests for PerformancePipeline initialization."""

    def test_initialization(self, performance_pipeline):
        """Test pipeline initialization and table IDs."""
        assert performance_pipeline.job_name == "performance_pipeline"
        assert "stg_performance_import_test" in performance_pipeline.staging_table_id
        assert "summary_strategy_performance_test" in performance_pipeline.fact_table_id
        assert performance_pipeline.schema_model == StrategyPerformance


class TestPerformancePipelineExtract:
    """Tests for PerformancePipeline.extract()."""

    def test_extract_generates_correct_query(self, performance_pipeline):
        """Verify that extract generates the correct SQL aggregation query."""
        mock_bq = performance_pipeline.bq_client

        # Mock T-1 availability check
        mock_query_check = MagicMock()
        mock_query_check.result.return_value = [MagicMock(cnt=1)]

        mock_query_extract = MagicMock()
        mock_query_extract.result.return_value = []

        mock_bq.query.side_effect = [mock_query_check, mock_query_extract]

        performance_pipeline.extract()

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

    def test_extract_targets_t_minus_1(self, performance_pipeline):
        """Verify that extract targets T-1 data."""
        mock_bq = performance_pipeline.bq_client

        mock_query_check = MagicMock()
        mock_query_check.result.return_value = [MagicMock(cnt=1)]

        mock_query_extract = MagicMock()
        mock_query_extract.result.return_value = []

        mock_bq.query.side_effect = [mock_query_check, mock_query_extract]

        performance_pipeline.extract()

        queries = [call.args[0] for call in mock_bq.query.call_args_list]
        assert any("DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)" in q for q in queries)

    def test_extract_skips_if_no_data(self, performance_pipeline):
        """Verify that extract returns empty list if T-1 data is not available."""
        mock_bq = performance_pipeline.bq_client

        mock_query_check = MagicMock()
        mock_query_check.result.return_value = [MagicMock(cnt=0)]

        mock_bq.query.return_value = mock_query_check

        results = performance_pipeline.extract()
        assert results == []
        assert mock_bq.query.call_count == 1

    def test_extract_raises_on_bigquery_error(self, performance_pipeline):
        """Verify that extract re-raises BigQuery errors after logging."""
        mock_bq = performance_pipeline.bq_client

        # T-1 check passes
        mock_query_check = MagicMock()
        mock_query_check.result.return_value = [MagicMock(cnt=1)]

        # Extraction query fails
        mock_query_extract = MagicMock()
        mock_query_extract.result.side_effect = RuntimeError("BigQuery timeout")

        mock_bq.query.side_effect = [mock_query_check, mock_query_extract]

        with pytest.raises(RuntimeError, match="BigQuery timeout"):
            performance_pipeline.extract()


class TestCheckTMinus1Data:
    """Tests for PerformancePipeline._check_t_minus_1_data()."""

    def test_check_returns_false_on_exception(self, performance_pipeline):
        """Verify that _check_t_minus_1_data returns False on BigQuery error."""
        mock_bq = performance_pipeline.bq_client
        mock_bq.query.side_effect = RuntimeError("Connection refused")

        result = performance_pipeline._check_t_minus_1_data()
        assert result is False

    def test_check_returns_false_on_empty_result(self, performance_pipeline):
        """Verify that _check_t_minus_1_data returns False when result is None."""
        mock_bq = performance_pipeline.bq_client
        mock_query_job = MagicMock()
        mock_query_job.result.return_value = iter([])  # Empty iterator
        mock_bq.query.return_value = mock_query_job

        result = performance_pipeline._check_t_minus_1_data()
        assert result is False
