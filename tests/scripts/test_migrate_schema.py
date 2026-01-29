from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.scripts.migrate_schema import migrate_schema


@patch("crypto_signals.scripts.migrate_schema.SchemaGuardian")
@patch("crypto_signals.scripts.migrate_schema.bigquery.Client")
def test_migrate_schema_executes_single_alter_statement(
    mock_bq_client, mock_schema_guardian
):
    """
    Test that migrate_schema generates and executes a single, correct ALTER TABLE
    statement for all missing columns.
    """
    # Arrange
    mock_guardian_instance = MagicMock()
    mock_guardian_instance.validate_schema.return_value = (
        [("asset_class", "STRING"), ("side", "STRING")],
        [],
    )
    mock_schema_guardian.return_value = mock_guardian_instance

    mock_client_instance = MagicMock()
    mock_bq_client.return_value = mock_client_instance

    # Act
    migrate_schema("dummy_table", MagicMock())

    # Assert
    mock_client_instance.query.assert_called_once_with(
        "ALTER TABLE `dummy_table` ADD COLUMN `asset_class` STRING, ADD COLUMN `side` STRING"
    )


@patch("crypto_signals.scripts.migrate_schema.SchemaGuardian")
@patch("crypto_signals.scripts.migrate_schema.bigquery.Client")
def test_migrate_schema_no_missing_columns(mock_bq_client, mock_schema_guardian):
    """
    Test that migrate_schema does not execute any queries when there are no
    missing columns.
    """
    # Arrange
    mock_guardian_instance = MagicMock()
    mock_guardian_instance.validate_schema.return_value = ([], [])
    mock_schema_guardian.return_value = mock_guardian_instance

    mock_client_instance = MagicMock()
    mock_bq_client.return_value = mock_client_instance

    # Act
    migrate_schema("dummy_table", MagicMock())

    # Assert
    mock_client_instance.query.assert_not_called()


@patch("crypto_signals.scripts.migrate_schema.SchemaGuardian")
@patch("crypto_signals.scripts.migrate_schema.bigquery.Client")
def test_migrate_schema_only_type_mismatches(mock_bq_client, mock_schema_guardian):
    """
    Test that migrate_schema does not execute any queries when there are only
    type mismatches, as it only handles adding missing columns.
    """
    # Arrange
    mock_guardian_instance = MagicMock()
    mock_guardian_instance.validate_schema.return_value = (
        [],
        ["type_mismatch_error"],
    )
    mock_schema_guardian.return_value = mock_guardian_instance

    mock_client_instance = MagicMock()
    mock_bq_client.return_value = mock_client_instance

    # Act
    migrate_schema("dummy_table", MagicMock())

    # Assert
    mock_client_instance.query.assert_not_called()


@patch("crypto_signals.scripts.migrate_schema.SchemaGuardian")
@patch("crypto_signals.scripts.migrate_schema.bigquery.Client")
def test_migrate_schema_raises_on_alter_failure(mock_bq_client, mock_schema_guardian):
    """
    Test that migrate_schema raises an exception when ALTER TABLE fails.
    This ensures CI/CD correctly reports failure instead of silent success.
    """
    # Arrange
    mock_guardian_instance = MagicMock()
    mock_guardian_instance.validate_schema.return_value = (
        [("new_column", "STRING")],
        [],
    )
    mock_schema_guardian.return_value = mock_guardian_instance

    mock_client_instance = MagicMock()
    mock_client_instance.query.side_effect = Exception("BigQuery ALTER TABLE failed")
    mock_bq_client.return_value = mock_client_instance

    # Act & Assert
    with pytest.raises(Exception, match="BigQuery ALTER TABLE failed"):
        migrate_schema("dummy_table", MagicMock())
