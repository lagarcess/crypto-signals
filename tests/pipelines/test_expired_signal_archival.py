"""
Unit tests for the ExpiredSignalArchivalPipeline.
"""

import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
from crypto_signals.domain.schemas import AssetClass, OrderSide
from crypto_signals.pipelines.expired_signal_archival import ExpiredSignalArchivalPipeline


class TestExpiredSignalArchivalPipeline(unittest.TestCase):
    """
    Test suite for the ExpiredSignalArchivalPipeline.
    """

    def setUp(self):
        """
        Set up the test environment.
        """
        self.pipeline = ExpiredSignalArchivalPipeline()

    @patch("google.cloud.firestore.Client")
    def test_extract(self, mock_firestore_client):
        """
        Test the extract method.
        """
        mock_collection = MagicMock()
        mock_firestore_client.collection.return_value = mock_collection
        mock_collection.where.return_value.where.return_value.stream.return_value = [
            MagicMock(to_dict=lambda: {"signal_id": "1"}),
            MagicMock(to_dict=lambda: {"signal_id": "2"}),
        ]
        self.pipeline.firestore_client = mock_firestore_client

        data = self.pipeline.extract()

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["signal_id"], "1")

    @patch("crypto_signals.market.data_provider.MarketDataProvider")
    def test_transform(self, mock_market_provider):
        """
        Test the transform method.
        """
        raw_data = [
            {
                "ds": date(2023, 1, 1),
                "signal_id": "1",
                "strategy_id": "test_strategy",
                "symbol": "BTC/USD",
                "asset_class": AssetClass.CRYPTO,
                "side": OrderSide.BUY,
                "entry_price": 50000.0,
                "suggested_stop": 49000.0,
                "created_at": datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "valid_until": datetime(2023, 1, 2, 0, 0, 0, tzinfo=timezone.utc),
            }
        ]

        bars_df = pd.DataFrame(
            {"high": [51000.0], "low": [49000.0]},
            index=[pd.to_datetime("2023-01-01 12:00:00+00:00")],
        )
        mock_market_provider.get_daily_bars.return_value = bars_df
        self.pipeline.market_provider = mock_market_provider

        transformed_data = self.pipeline.transform(raw_data)

        self.assertEqual(len(transformed_data), 1)
        self.assertEqual(transformed_data[0]["signal_id"], "1")
        self.assertEqual(transformed_data[0]["max_mfe_during_validity"], 1000.0)
        self.assertAlmostEqual(transformed_data[0]["distance_to_trigger_pct"], -2.0)

    @patch("google.cloud.firestore.Client")
    def test_cleanup(self, mock_firestore_client):
        """
        Test the cleanup method.
        """
        data = [
            {
                "ds": date(2023, 1, 1),
                "signal_id": "1",
                "strategy_id": "test_strategy",
                "symbol": "BTC/USD",
                "asset_class": AssetClass.CRYPTO,
                "side": OrderSide.BUY,
                "entry_price": 50000.0,
                "suggested_stop": 49000.0,
                "valid_until": datetime(2023, 1, 2, 0, 0, 0, tzinfo=timezone.utc),
            }
        ]

        # The base class's `run` method re-validates the transformed data, so we
        # need to pass instances of the schema model to `cleanup`.
        cleanup_data = [self.pipeline.schema_model.model_validate(d) for d in data]

        mock_batch = MagicMock()
        mock_firestore_client.batch.return_value = mock_batch
        self.pipeline.firestore_client = mock_firestore_client

        self.pipeline.cleanup(cleanup_data)

        mock_batch.delete.assert_called_once()
        mock_batch.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
