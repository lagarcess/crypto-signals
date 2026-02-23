"""Shared fixtures for pipeline tests."""

from unittest.mock import patch

import pytest
from crypto_signals.pipelines.performance import PerformancePipeline


@pytest.fixture
def performance_pipeline():
    """Create a PerformancePipeline instance with mocked BigQuery client."""
    with patch("google.cloud.bigquery.Client"):
        with patch("crypto_signals.pipelines.base.get_settings") as mock_settings:
            mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
            mock_settings.return_value.ENVIRONMENT = "DEV"
            mock_settings.return_value.SCHEMA_GUARDIAN_STRICT_MODE = True
            mock_settings.return_value.SCHEMA_MIGRATION_AUTO = True
            mock_settings.return_value.PERFORMANCE_BASELINE_CAPITAL = 100000.0
            return PerformancePipeline()
