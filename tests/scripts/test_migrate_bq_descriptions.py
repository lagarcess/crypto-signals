import unittest
from typing import ClassVar
from unittest.mock import MagicMock, patch

from crypto_signals.config import Settings
from crypto_signals.scripts.maintenance import migrate_bq_descriptions
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from pydantic import BaseModel, Field


# Dummy Models for Testing
class NestedModel(BaseModel):
    """Nested Model doc"""

    nested_field: str = Field(description="Nested field description")


class MockModel(BaseModel):
    """Test Table Description"""

    _bq_table_name: ClassVar[str] = "mock_table"
    field1: str = Field(description="Field 1 description")
    nested: NestedModel


class MockModelNoTable(BaseModel):
    field1: str


class TestMigrateBqDescriptions(unittest.TestCase):
    @patch("crypto_signals.scripts.maintenance.migrate_bq_descriptions.schemas")
    def test_find_analytics_models(self, mock_schemas):
        mock_schemas.MockModel = MockModel
        mock_schemas.MockModelNoTable = MockModelNoTable

        with patch(
            "inspect.getmembers",
            return_value=[
                ("MockModel", MockModel),
                ("MockModelNoTable", MockModelNoTable),
            ],
        ):
            models = migrate_bq_descriptions.find_analytics_models()
            self.assertIn(MockModel, models)
            self.assertNotIn(MockModelNoTable, models)

    @patch("crypto_signals.scripts.maintenance.migrate_bq_descriptions.get_settings")
    def test_resolve_table_prod(self, mock_get_settings):
        # Setup
        mock_settings = MagicMock(spec=Settings)
        mock_settings.GOOGLE_CLOUD_PROJECT = "test-project"
        mock_settings.BIGQUERY_DATASET = "test_dataset"
        mock_settings.ENVIRONMENT = "PROD"
        mock_settings.TEST_MODE = False
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_table = MagicMock(spec=bigquery.Table)
        mock_table.table_id = "fact_trades"
        mock_client.get_table.return_value = mock_table

        # Execute
        table = migrate_bq_descriptions.resolve_table(mock_client, "fact_trades")

        # Verify
        self.assertEqual(table, mock_table)
        mock_client.get_table.assert_called_with("test-project.test_dataset.fact_trades")

    @patch("crypto_signals.scripts.maintenance.migrate_bq_descriptions.get_settings")
    def test_resolve_table_dev_fuzzy(self, mock_get_settings):
        # Setup
        mock_settings = MagicMock(spec=Settings)
        mock_settings.GOOGLE_CLOUD_PROJECT = "test-project"
        mock_settings.BIGQUERY_DATASET = "test_dataset"
        mock_settings.ENVIRONMENT = "DEV"
        mock_settings.TEST_MODE = True
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_table = MagicMock(spec=bigquery.Table)

        # Simulate not found for _test, found for base
        def side_effect(table_id):
            if table_id.endswith("_test"):
                raise NotFound("Not found")
            return mock_table

        mock_client.get_table.side_effect = side_effect

        # Execute
        table = migrate_bq_descriptions.resolve_table(mock_client, "fact_trades")

        # Verify
        self.assertEqual(table, mock_table)
        self.assertEqual(mock_client.get_table.call_count, 2)

    def test_update_table_description(self):
        # Setup
        mock_client = MagicMock()
        mock_table = MagicMock(spec=bigquery.Table)
        mock_table.description = "Old Description"
        mock_table.project = "p"
        mock_table.dataset_id = "d"
        mock_table.table_id = "t"

        # Mock Schema
        # Top level field
        field1 = bigquery.SchemaField("field1", "STRING", description="Old field1")
        # Nested field (RECORD)
        nested_subfield = bigquery.SchemaField(
            "nested_field", "STRING", description="Old nested"
        )
        nested = bigquery.SchemaField("nested", "RECORD", fields=[nested_subfield])

        mock_table.schema = [field1, nested]

        # Execute
        migrate_bq_descriptions.update_table_description(
            mock_client, mock_table, MockModel
        )

        # Verify
        # 1. Table description updated?
        self.assertEqual(mock_table.description, "Test Table Description")

        # 2. Schema updated?
        # Expecting client.update_table to be called once with both fields
        mock_client.update_table.assert_called_once()
        args, _ = mock_client.update_table.call_args
        updated_table, fields = args

        self.assertIn("description", fields)
        self.assertIn("schema", fields)

        # Check new schema content
        new_schema = updated_table.schema
        self.assertEqual(len(new_schema), 2)

        # Check field1 description
        self.assertEqual(new_schema[0].description, "Field 1 description")

        # Check nested field description
        self.assertEqual(new_schema[1].fields[0].description, "Nested field description")
