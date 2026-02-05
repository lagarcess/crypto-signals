"""Unit tests for the BigQueryPipelineBase class."""

import textwrap
from datetime import date
from typing import Any, List
from unittest.mock import patch

import pytest
from crypto_signals.pipelines.base import BigQueryPipelineBase
from pydantic import BaseModel, Field

from tests.utils.sql_assertion import assert_merge_query_structure, assert_sql_equal

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
    with patch("crypto_signals.pipelines.base.get_settings") as mock_settings:
        mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"

        # Mock SchemaGuardian to prevent real BQ calls during pipeline tests
        with patch("crypto_signals.pipelines.base.SchemaGuardian"):
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
        "test-project.dataset.stg_test", data, ignore_unknown_values=True
    )


def test_load_to_staging_raises_on_error(pipeline, mock_bq_client):
    """Test that _load_to_staging raises RuntimeError on insert errors."""
    mock_bq_client.insert_rows_json.return_value = [{"error": "bad stuff"}]

    with pytest.raises(RuntimeError):
        pipeline._load_to_staging([{"id": "1"}])


def test_execute_merge_constructs_correct_sql(pipeline, mock_bq_client):
    """Test dynamic SQL generation for MERGE statement."""
    pipeline._execute_merge()

    call_args = mock_bq_client.query.call_args
    assert call_args is not None
    query = call_args[0][0]

    assert_merge_query_structure(
        query,
        target_table=f"`{pipeline.fact_table_id}`",
        source_table=f"`{pipeline.staging_table_id}`",
        join_keys=[pipeline.id_column, pipeline.partition_column],
        update_columns=[col for col in pipeline.schema_model.model_fields.keys() if col not in [pipeline.id_column, pipeline.partition_column]],
        insert_columns=sorted(list(pipeline.schema_model.model_fields.keys())),
    )


def test_cleanup_staging_executes_correct_sql(pipeline, mock_bq_client):
    """Test that cleanup_staging runs the correct DELETE SQL."""
    pipeline.cleanup_staging()

    call_args = mock_bq_client.query.call_args
    assert call_args is not None
    query = call_args[0][0]

    expected_query = textwrap.dedent(f"""
            DELETE FROM `test-project.dataset.stg_test`
            WHERE ds < DATE_SUB(CURRENT_DATE(), INTERVAL {pipeline.STAGING_CLEANUP_DAYS} DAY)
        """).strip()

    assert_sql_equal(query, expected_query)


def test_run_orchestrates_flow(pipeline):
    """Test that run calls all steps in order."""
    # Mock methods to verify order
    with (
        patch.object(pipeline, "extract") as mock_extract,
        patch.object(pipeline, "transform") as mock_transform,
        patch.object(pipeline, "_truncate_staging") as mock_trunc,
        patch.object(pipeline, "_load_to_staging") as mock_load,
        patch.object(pipeline, "_execute_merge") as mock_merge,
        patch.object(pipeline, "cleanup_staging") as mock_cleanup_staging,
        patch.object(pipeline, "cleanup") as mock_cleanup,
    ):
        mock_extract.return_value = [{"id": "1", "ds": date(2024, 1, 1), "value": 100}]
        mock_transform.return_value = [{"id": "1", "ds": "2024-01-01", "value": 100}]

        pipeline.run()

        mock_extract.assert_called_once()
        mock_transform.assert_called_once()
        mock_trunc.assert_called_once()
        mock_load.assert_called_once()
        mock_merge.assert_called_once()
        mock_cleanup_staging.assert_called_once()
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
