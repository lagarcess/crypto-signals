from typing import Optional
from unittest.mock import MagicMock

import pytest
from crypto_signals.engine.schema_guardian import (
    Clustering,
    SchemaGuardian,
    SchemaMismatchError,
    TimePartitioning,
)
from google.cloud import bigquery
from pydantic import BaseModel

# --- Mocks & Fixtures ---


import datetime


class SimpleModel(BaseModel):
    name: str
    age: int
    score: float
    is_active: bool
    some_date: datetime.date


class ComplexModel(BaseModel):
    id: str
    meta: Optional[str] = None
    tags: list[str] = []  # Lists not fully supported in V1 but good to check


@pytest.fixture
def mock_bq_client():
    return MagicMock(spec=bigquery.Client)


@pytest.fixture
def guardian(mock_bq_client):
    return SchemaGuardian(bq_client=mock_bq_client, strict_mode=True)


# --- Tests ---


def test_validate_schema_success(guardian, mock_bq_client):
    """Test that validation passes when schema matches perfectly."""
    # Mock BigQuery Table Schema
    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("age", "INTEGER"),
        bigquery.SchemaField("score", "FLOAT"),
        bigquery.SchemaField("is_active", "BOOLEAN"),
        bigquery.SchemaField("some_date", "DATE"),
    ]
    mock_bq_client.get_table.return_value = mock_table

    # Should not raise
    guardian.validate_schema("project.dataset.table", SimpleModel)


def test_validate_schema_missing_column(guardian, mock_bq_client):
    """Test that validation fails when a column is missing in BigQuery."""
    mock_table = MagicMock()
    # "age" is missing
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("score", "FLOAT"),
        bigquery.SchemaField("is_active", "BOOLEAN"),
    ]
    mock_bq_client.get_table.return_value = mock_table

    with pytest.raises(SchemaMismatchError) as exc:
        guardian.validate_schema("project.dataset.table", SimpleModel)

    assert "Missing columns" in str(exc.value)
    assert "age" in str(exc.value)


def test_validate_schema_type_mismatch(guardian, mock_bq_client):
    """Test that validation fails when a column has wrong type."""
    mock_table = MagicMock()
    # "age" is BOOLEAN instead of INTEGER
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("age", "BOOLEAN"),
        bigquery.SchemaField("score", "FLOAT"),
        bigquery.SchemaField("is_active", "BOOLEAN"),
    ]
    mock_bq_client.get_table.return_value = mock_table

    with pytest.raises(SchemaMismatchError) as exc:
        guardian.validate_schema("project.dataset.table", SimpleModel)

    assert "Type mismatch" in str(exc.value)
    assert "age" in str(exc.value)


def test_validate_schema_compatible_types_float_numeric(guardian, mock_bq_client):
    """Test that FLOAT matches NUMERIC/BIGNUMERIC (Fuzzy Match)."""
    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("age", "INTEGER"),
        bigquery.SchemaField("score", "NUMERIC"),  # Compatible with float
        bigquery.SchemaField("is_active", "BOOLEAN"),
        bigquery.SchemaField("some_date", "DATE"),
    ]
    mock_bq_client.get_table.return_value = mock_table

    # Should not raise
    guardian.validate_schema("project.dataset.table", SimpleModel)


def test_validate_schema_strict_mode_false(mock_bq_client):
    """Test that strict_mode=False only logs errors but doesn't raise."""
    guardian_lazy = SchemaGuardian(bq_client=mock_bq_client, strict_mode=False)

    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
    ]  # Missing fields
    mock_bq_client.get_table.return_value = mock_table

    # Should NOT raise
    guardian_lazy.validate_schema("project.dataset.table", SimpleModel)


def test_table_not_found(guardian, mock_bq_client):
    """Test behavior when table doesn't exist."""
    mock_bq_client.get_table.side_effect = RuntimeError("Not found")

    with pytest.raises(RuntimeError, match="Not found"):
        guardian.validate_schema("project.dataset.table", SimpleModel)


class ChildModel(BaseModel):
    sub_name: str
    sub_val: int


class ParentModel(BaseModel):
    id: str
    child: ChildModel


def test_validate_nested_schema(guardian, mock_bq_client):
    """Test (currently failing) support for Nested Models -> RECORD."""
    mock_table = MagicMock()
    # BigQuery represents nested fields as type=RECORD with a 'fields' attribute
    child_field = bigquery.SchemaField(
        "child",
        "RECORD",
        fields=[
            bigquery.SchemaField("sub_name", "STRING"),
            bigquery.SchemaField("sub_val", "INTEGER"),
        ],
    )

    mock_table.schema = [bigquery.SchemaField("id", "STRING"), child_field]
    mock_bq_client.get_table.return_value = mock_table

    # This should pass if recursion is implemented, fail otherwise
    guardian.validate_schema("project.dataset.table", ParentModel)


def test_validate_schema_partitioning_and_clustering_success(guardian, mock_bq_client):
    """Test that validation passes with correct partitioning and clustering."""
    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("age", "INTEGER"),
        bigquery.SchemaField("score", "FLOAT"),
        bigquery.SchemaField("is_active", "BOOLEAN"),
        bigquery.SchemaField("some_date", "DATE"),
    ]
    mock_table.time_partitioning = MagicMock(type_="DAY", field="some_date")
    mock_table.clustering_fields = ["name"]
    mock_bq_client.get_table.return_value = mock_table

    # Should not raise
    guardian.validate_schema(
        "project.dataset.table",
        SimpleModel,
        expected_partitioning=TimePartitioning(type="DAY", field="some_date"),
        expected_clustering=Clustering(fields=["name"]),
    )


def test_validate_schema_partitioning_missing(guardian, mock_bq_client):
    """Test failure when partitioning is expected but not configured."""
    mock_table = MagicMock()
    mock_table.schema = [bigquery.SchemaField("name", "STRING")]
    mock_table.time_partitioning = None  # No partitioning
    mock_bq_client.get_table.return_value = mock_table

    with pytest.raises(SchemaMismatchError, match="Partitioning Validation Failed"):
        guardian.validate_schema(
            "project.dataset.table",
            SimpleModel,
            expected_partitioning=TimePartitioning(type="DAY", field="some_date"),
        )


def test_validate_schema_clustering_missing(guardian, mock_bq_client):
    """Test failure when clustering is expected but not configured."""
    mock_table = MagicMock()
    mock_table.schema = [bigquery.SchemaField("name", "STRING")]
    mock_table.time_partitioning = MagicMock(type_="DAY", field="some_date")
    mock_table.clustering_fields = None  # No clustering
    mock_bq_client.get_table.return_value = mock_table

    with pytest.raises(SchemaMismatchError, match="Clustering Validation Failed"):
        guardian.validate_schema(
            "project.dataset.table",
            SimpleModel,
            expected_partitioning=TimePartitioning(type="DAY", field="some_date"),
            expected_clustering=Clustering(fields=["name"]),
        )


def test_validate_schema_clustering_mismatch(guardian, mock_bq_client):
    """Test failure when clustering keys are different."""
    mock_table = MagicMock()
    mock_table.schema = [bigquery.SchemaField("name", "STRING")]
    mock_table.time_partitioning = MagicMock(type_="DAY", field="some_date")
    mock_table.clustering_fields = ["wrong_field"]  # Mismatched key
    mock_bq_client.get_table.return_value = mock_table

    with pytest.raises(SchemaMismatchError, match="Clustering Validation Failed"):
        guardian.validate_schema(
            "project.dataset.table",
            SimpleModel,
            expected_partitioning=TimePartitioning(type="DAY", field="some_date"),
            expected_clustering=Clustering(fields=["name"]),
        )
