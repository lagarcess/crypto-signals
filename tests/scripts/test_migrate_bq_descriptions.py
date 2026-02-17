import unittest
from typing import ClassVar
from unittest.mock import MagicMock, call, patch

from crypto_signals.config import Settings
from crypto_signals.scripts.maintenance import migrate_bq_descriptions
from google.api_core.exceptions import NotFound
from pydantic import BaseModel


# Dummy Models for Testing
class MockModel(BaseModel):
    """Test Table Description"""

    _bq_table_name: ClassVar[str] = "mock_table"
    field1: str


class MockModelNoTable(BaseModel):
    field1: str


class TestMigrateBqDescriptions(unittest.TestCase):
    @patch("crypto_signals.scripts.maintenance.migrate_bq_descriptions.schemas")
    def test_find_analytics_models(self, mock_schemas):
        # Setup mock schemas module
        mock_schemas.MockModel = MockModel
        mock_schemas.MockModelNoTable = MockModelNoTable
        # We need to ensure inspect.getmembers returns these
        # Since inspect.getmembers iterates over attributes, we can just set them on the mock

        # However, inspect.getmembers on a wrapper might be tricky.
        # Easier to integration test or mock inspect.getmembers

        # Let's try mocking inspect.getmembers
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
    def test_resolve_table_id_prod(self, mock_get_settings):
        mock_settings = MagicMock(spec=Settings)
        mock_settings.GOOGLE_CLOUD_PROJECT = "test-project"
        mock_settings.BIGQUERY_DATASET = "test_dataset"
        mock_settings.ENVIRONMENT = "PROD"
        mock_settings.TEST_MODE = False
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()

        # Test Success
        table_id = migrate_bq_descriptions.resolve_table_id(mock_client, "fact_trades")
        self.assertEqual(table_id, "test-project.test_dataset.fact_trades")
        mock_client.get_table.assert_called_with("test-project.test_dataset.fact_trades")

    @patch("crypto_signals.scripts.maintenance.migrate_bq_descriptions.get_settings")
    def test_resolve_table_id_dev_fuzzy(self, mock_get_settings):
        mock_settings = MagicMock(spec=Settings)
        mock_settings.GOOGLE_CLOUD_PROJECT = "test-project"
        mock_settings.BIGQUERY_DATASET = "test_dataset"
        mock_settings.ENVIRONMENT = "DEV"
        mock_settings.TEST_MODE = True
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()

        # Helper to simulate NotFound for first call, Success for second
        def side_effect(table_id):
            if table_id.endswith("_test"):
                raise NotFound("Not found")
            return MagicMock()

        mock_client.get_table.side_effect = side_effect

        # Should try _test first (fail), then base (succeed)
        table_id = migrate_bq_descriptions.resolve_table_id(mock_client, "fact_trades")

        self.assertEqual(table_id, "test-project.test_dataset.fact_trades")
        self.assertEqual(mock_client.get_table.call_count, 2)
        mock_client.get_table.assert_has_calls(
            [
                call("test-project.test_dataset.fact_trades_test"),
                call("test-project.test_dataset.fact_trades"),
            ]
        )

    def test_update_table_description(self):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_table.description = "Old Description"
        mock_table.schema = []
        mock_client.get_table.return_value = mock_table

        migrate_bq_descriptions.update_table_description(
            mock_client, "table_id", MockModel
        )

        # Check Table Update
        self.assertEqual(mock_table.description, "Test Table Description")
        mock_client.update_table.assert_any_call(mock_table, ["description"])
