"""
Integration tests for exit price capture and BigQuery repair (Issue #141).

Tests cover:
- Full trade lifecycle with exit price verification
- Multi-stage PnL calculation
- PricePatchPipeline historical repair
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.pipelines.price_patch import PricePatchPipeline


@pytest.mark.integration
class TestExitPriceIntegration:
    """End-to-end tests for exit price capture and archival."""

    def test_crypto_exit_to_bigquery(self, alpaca_client, firestore_repo, bq_client):
        """Test full lifecycle: crypto exit → Firestore → BigQuery."""
        pytest.skip("Requires live Alpaca/Firestore/BigQuery connections")

        # 1. Create position (crypto, no bracket order)
        # 2. Close position via close_position_emergency()
        # 3. Verify exit_fill_price in Firestore
        # 4. Run trade_archival pipeline
        # 5. Verify pnl_usd in BigQuery (non-zero)
        # 6. Verify exit_price_finalized = TRUE

    def test_scale_out_pnl_calculation(self, alpaca_client, firestore_repo):
        """Test multi-stage PnL with scale-outs."""
        pytest.skip("Requires live Alpaca/Firestore connections")

        # 1. Create position
        # 2. Scale out 50% at TP1 ($100)
        # 3. Scale out 50% at TP2 ($110)
        # 4. Verify scaled_out_prices has 2 entries
        # 5. Verify exit_fill_price = $105 (weighted average)
        # 6. Verify PnL calculation uses weighted average


@pytest.mark.integration
class TestPricePatchPipeline:
    """Test BigQuery historical repair pipeline."""

    def test_price_patch_query(self):
        """Test price patch pipeline query logic."""
        # Arrange
        with patch("crypto_signals.config.get_settings") as mock_settings:
            mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
            mock_settings.return_value.ENVIRONMENT = "PROD"

            pipeline = PricePatchPipeline()

            # Mock BigQuery client
            mock_bq_client = MagicMock()
            pipeline.bq_client = mock_bq_client

            # Mock query results
            mock_row = {
                "trade_id": "trade-123",
                "symbol": "BTC/USD",
                "asset_class": "CRYPTO",
                "entry_time": datetime.now(timezone.utc),
                "exit_time": datetime.now(timezone.utc),
                "exit_order_id": "order-abc",
                "entry_fill_price": 50000.0,
                "current_exit_price": 0.0,
                "ds": datetime.now(timezone.utc).date(),
            }

            mock_query_job = MagicMock()
            mock_query_job.result.return_value = [mock_row]
            mock_bq_client.query.return_value = mock_query_job

            # Act
            unfinalized_trades = pipeline._query_unfinalized_trades()

            # Assert
            assert len(unfinalized_trades) == 1
            assert unfinalized_trades[0]["trade_id"] == "trade-123"
            assert unfinalized_trades[0]["exit_order_id"] == "order-abc"
            assert unfinalized_trades[0]["current_exit_price"] == 0.0

    def test_price_patch_update(self):
        """Test price patch pipeline update logic."""
        # Arrange
        with patch("crypto_signals.config.get_settings") as mock_settings:
            mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
            mock_settings.return_value.ENVIRONMENT = "PROD"

            pipeline = PricePatchPipeline()

            # Mock BigQuery client
            mock_bq_client = MagicMock()
            pipeline.bq_client = mock_bq_client

            # Mock execution engine
            mock_engine = MagicMock()
            pipeline.execution_engine = mock_engine

            # Mock order details from Alpaca
            mock_order = MagicMock()
            mock_order.filled_avg_price = 51000.0
            mock_order.status = "filled"
            mock_engine.get_order_details.return_value = mock_order

            # Mock BigQuery update
            mock_update_job = MagicMock()
            mock_update_job.result.return_value = None
            mock_bq_client.query.return_value = mock_update_job

            trade = {
                "trade_id": "trade-123",
                "symbol": "BTC/USD",
                "exit_order_id": "order-abc",
                "entry_fill_price": 50000.0,
                "current_exit_price": 0.0,
                "qty": 1.0,
            }

            # Act
            result = pipeline._patch_trade_price(trade)

            # Assert
            assert result is True
            mock_engine.get_order_details.assert_called_once_with("order-abc")
            mock_bq_client.query.assert_called_once()

            # Verify query parameters
            call_args = mock_bq_client.query.call_args
            job_config = call_args[1]["job_config"]
            params = {p.name: p.value for p in job_config.query_parameters}

            assert params["actual_exit_price"] == 51000.0
            assert params["trade_id"] == "trade-123"
            assert params["pnl_usd"] == pytest.approx(
                1000.0, rel=0.01
            )  # (51000 - 50000) * 1.0

    def test_price_patch_full_pipeline(self):
        """Test full price patch pipeline execution."""
        # Arrange
        with patch("crypto_signals.config.get_settings") as mock_settings:
            mock_settings.return_value.GOOGLE_CLOUD_PROJECT = "test-project"
            mock_settings.return_value.ENVIRONMENT = "PROD"

            pipeline = PricePatchPipeline()

            # Mock query to return 2 trades
            pipeline._query_unfinalized_trades = MagicMock(
                return_value=[
                    {"trade_id": "trade-1", "exit_order_id": "order-1"},
                    {"trade_id": "trade-2", "exit_order_id": "order-2"},
                ]
            )

            # Mock patch to succeed for first, fail for second
            pipeline._patch_trade_price = MagicMock(side_effect=[True, False])

            # Act
            patched_count = pipeline.run()

            # Assert
            assert patched_count == 1  # Only first succeeded
            assert pipeline._patch_trade_price.call_count == 2


@pytest.fixture
def alpaca_client():
    """Mock Alpaca client."""
    return MagicMock()


@pytest.fixture
def firestore_repo():
    """Mock Firestore repository."""
    return MagicMock()


@pytest.fixture
def bq_client():
    """Mock BigQuery client."""
    return MagicMock()
