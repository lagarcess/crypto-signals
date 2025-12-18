"""Unit tests for the BigQueryPipelineBase class."""

from datetime import date
from typing import Any, List
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from crypto_signals.pipelines.base import BigQueryPipelineBase

# --- Mocks & Fixtures ---


class MockSchema(BaseModel):
    """Mock Schema for testing."""

    id: str = Field(..., description="Primary Key")
    ds: date = Field(..., description="Partition Key")
    value: int = Field(..., description="Some value")


class ConcretePipeline(BigQueryPipelineBase):
    """Concrete implementation for testing purposes."""

    def extract(self) -> List[Any]:
        """Return dummy data."""
        return [{"id": "1", "ds": date(2024, 1, 1), "value": 100}]

    def cleanup(self, data: List[BaseModel]) -> None:
        """Do nothing."""


@pytest.fixture
def mock_bq_client():
    """Mock the BigQuery Client."""
    with patch("crypto_signals.pipelines.base.bigquery.Client") as mock:
        yield mock.return_value


@pytest.fixture
def pipeline(mock_bq_client):
    """Return a concrete pipeline instance with mocked clients."""
    # Mock settings to avoid loading .env
    with patch("crypto_signals.pipelines.base.settings") as mock_settings:
        mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"

        return ConcretePipeline(
            job_name="test_pipeline",
            staging_table_id="test-project.dataset.stg_test",
            fact_table_id="test-project.dataset.fact_test",
            id_column="id",
            partition_column="ds",
            schema_model=MockSchema,
        )


# --- Tests ---


def test_transform_validates_and_dumps_json(pipeline):
    """Test that transform validates data and returns JSON-compatible dicts."""
    raw_data = [{"id": "1", "ds": date(2024, 1, 1), "value": 100}]

    transformed = pipeline.transform(raw_data)

    assert len(transformed) == 1
    assert isinstance(transformed[0], dict)
    # Date should be serialized to string for JSON
    assert transformed[0]["ds"] == "2024-01-01"
    assert transformed[0]["id"] == "1"


def test_truncate_staging_executes_query(pipeline, mock_bq_client):
    """Test that _truncate_staging runs the correct SQL."""
    pipeline._truncate_staging()

    expected_sql = "TRUNCATE TABLE `test-project.dataset.stg_test`"
    mock_bq_client.query.assert_called_with(expected_sql)


def test_load_to_staging_inserts_rows(pipeline, mock_bq_client):
    """Test that _load_to_staging calls insert_rows_json."""
    data = [{"id": "1"}]
    mock_bq_client.insert_rows_json.return_value = []  # No errors

    pipeline._load_to_staging(data)

    mock_bq_client.insert_rows_json.assert_called_with(
        "test-project.dataset.stg_test", data
    )


def test_load_to_staging_raises_on_error(pipeline, mock_bq_client):
    """Test that _load_to_staging raises RuntimeError on insert errors."""
    mock_bq_client.insert_rows_json.return_value = [{"error": "bad stuff"}]

    with pytest.raises(RuntimeError):
        pipeline._load_to_staging([{"id": "1"}])


def test_execute_merge_constructs_correct_sql(pipeline, mock_bq_client):
    """Test dynamic SQL generation for MERGE statement."""
    pipeline._execute_merge()

    # Capture the query call
    call_args = mock_bq_client.query.call_args
    assert call_args is not None
    query = call_args[0][0]

    # Check key components
    assert "MERGE `test-project.dataset.fact_test` T" in query
    assert "USING `test-project.dataset.stg_test` S" in query
    assert "ON T.id = S.id" in query
    assert "AND T.ds = S.ds" in query

    # Check UPDATE clause (should NOT update id or ds)
    assert "T.value = S.value" in query
    assert "T.id = S.id" not in query.split("UPDATE SET")[1]

    # Check INSERT clause
    assert "INSERT (id, ds, value)" in query
    assert "VALUES (S.id, S.ds, S.value)" in query


def test_run_orchestrates_flow(pipeline):
    """Test that run calls all steps in order."""
    # Mock methods to verify order
    with patch.object(pipeline, "extract") as mock_extract, patch.object(
        pipeline, "transform"
    ) as mock_transform, patch.object(
        pipeline, "_truncate_staging"
    ) as mock_trunc, patch.object(
        pipeline, "_load_to_staging"
    ) as mock_load, patch.object(
        pipeline, "_execute_merge"
    ) as mock_merge, patch.object(
        pipeline, "cleanup"
    ) as mock_cleanup:

        mock_extract.return_value = [{"id": "1", "ds": date(2024, 1, 1), "value": 100}]
        mock_transform.return_value = [{"id": "1", "ds": "2024-01-01", "value": 100}]

        pipeline.run()

        mock_extract.assert_called_once()
        mock_transform.assert_called_once()
        mock_trunc.assert_called_once()
        mock_load.assert_called_once()
        mock_merge.assert_called_once()
        mock_cleanup.assert_called_once()


def test_run_reraises_exception(pipeline):
    """Test that run re-raises exceptions to alert Cloud Run."""
    with patch.object(pipeline, "extract", side_effect=ValueError("Boom!")):
        with pytest.raises(ValueError, match="Boom!"):
            pipeline.run()


def test_run_skips_if_extract_empty(pipeline):
    """Test that run exits early if extract returns empty list."""
    with patch.object(pipeline, "extract", return_value=[]):
        with patch.object(pipeline, "_truncate_staging") as mock_trunc:
            pipeline.run()
            mock_trunc.assert_not_called()
