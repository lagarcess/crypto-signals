from typing import Optional
from unittest.mock import MagicMock

import pytest
from crypto_signals.engine.schema_guardian import SchemaGuardian, SchemaMismatchError
from google.cloud import bigquery
from pydantic import BaseModel

# --- Mocks & Fixtures ---


class SimpleModel(BaseModel):
    name: str
    age: int
    score: float
    is_active: bool


class ComplexModel(BaseModel):
    id: str
    meta: Optional[str] = None
    tags: list[str] = []  # Lists not fully supported in V1 but good to check


class PartitionModel(BaseModel):
    name: str
    ds: str


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


def test_validate_schema_partitioning_success(guardian, mock_bq_client):
    """Test that validation passes when partitioning is required and present."""
    mock_table = MagicMock()
    # Mock schema
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("ds", "STRING"),
    ]
    # Mock partitioning
    mock_table.time_partitioning = bigquery.TimePartitioning(field="ds")

    mock_bq_client.get_table.return_value = mock_table

    guardian.validate_schema(
        "project.dataset.table", PartitionModel, require_partitioning=True
    )


def test_validate_schema_partitioning_missing(guardian, mock_bq_client):
    """Test that validation fails when partitioning is required but missing."""
    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("ds", "STRING"),
    ]
    # No partitioning
    mock_table.time_partitioning = None
    mock_table.range_partitioning = None  # Also check range partitioning?

    mock_bq_client.get_table.return_value = mock_table

    with pytest.raises(SchemaMismatchError) as exc:
        guardian.validate_schema(
            "project.dataset.table", PartitionModel, require_partitioning=True
        )

    assert "Table is not partitioned" in str(exc.value)


def test_validate_schema_clustering_success(guardian, mock_bq_client):
    """Test that validation passes when clustering matches."""
    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("ds", "STRING"),
    ]
    mock_table.clustering_fields = ["name"]

    mock_bq_client.get_table.return_value = mock_table

    guardian.validate_schema(
        "project.dataset.table", PartitionModel, clustering_fields=["name"]
    )


def test_validate_schema_clustering_mismatch(guardian, mock_bq_client):
    """Test that validation fails when clustering does not match."""
    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("ds", "STRING"),
    ]
    # Actual is ["ds"], expected is ["name"]
    mock_table.clustering_fields = ["ds"]

    mock_bq_client.get_table.return_value = mock_table

    with pytest.raises(SchemaMismatchError) as exc:
        guardian.validate_schema(
            "project.dataset.table", PartitionModel, clustering_fields=["name"]
        )

    assert "Clustering mismatch" in str(exc.value)


def test_validate_schema_clustering_missing_on_table(guardian, mock_bq_client):
    """Test that validation fails when clustering is expected but table has none."""
    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("ds", "STRING"),
    ]
    mock_table.clustering_fields = None

    mock_bq_client.get_table.return_value = mock_table

    with pytest.raises(SchemaMismatchError) as exc:
        guardian.validate_schema(
            "project.dataset.table", PartitionModel, clustering_fields=["name"]
        )

    assert "Clustering mismatch" in str(exc.value)
