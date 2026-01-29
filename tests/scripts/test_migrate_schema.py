
from unittest.mock import MagicMock, patch

from crypto_signals.scripts.migrate_schema import migrate_schema


@patch("crypto_signals.scripts.migrate_schema.SchemaGuardian")
@patch("crypto_signals.scripts.migrate_schema.bigquery.Client")
def test_migrate_schema_executes_alter_statements(mock_bq_client, mock_schema_guardian):
    """
    Test that migrate_schema generates and executes the correct ALTER TABLE
    statements for each missing column identified by the refactored SchemaGuardian.
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
    assert mock_client_instance.query.call_count == 2
    mock_client_instance.query.assert_any_call(
        "ALTER TABLE `dummy_table` ADD COLUMN asset_class STRING"
    )
    mock_client_instance.query.assert_any_call(
        "ALTER TABLE `dummy_table` ADD COLUMN side STRING"
    )
