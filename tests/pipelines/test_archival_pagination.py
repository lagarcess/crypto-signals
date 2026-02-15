import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from crypto_signals.pipelines.trade_archival import TradeArchivalPipeline


class TestArchivalPagination(unittest.TestCase):
    @patch("crypto_signals.pipelines.trade_archival.get_settings")
    @patch("crypto_signals.pipelines.trade_archival.firestore")
    @patch("crypto_signals.pipelines.trade_archival.get_trading_client")
    @patch("crypto_signals.pipelines.trade_archival.get_stock_data_client")
    @patch("crypto_signals.pipelines.trade_archival.get_crypto_data_client")
    @patch("crypto_signals.engine.execution.ExecutionEngine")
    def test_transform_paginates_activities(
        self,
        mock_execution_engine,
        mock_get_crypto,
        mock_get_stock,
        mock_get_trading,
        mock_firestore,
        mock_settings,
    ):
        # Setup
        mock_settings.return_value.ENVIRONMENT = "PROD"
        mock_alpaca = MagicMock()
        mock_get_trading.return_value = mock_alpaca

        # Mock Execution Engine Fee Tier (prevent crash on fallback)
        mock_execution_engine.return_value.get_current_fee_tier.return_value = {
            "tier_name": "Tier 0",
            "taker_fee_pct": 0.1,
        }

        # Mock Position Data (2 positions, one recent, one old)
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=5)

        raw_data = [
            {
                "position_id": "pos_recent",
                "ds": now.date().isoformat(),
                "account_id": "paper",
                "strategy_id": "strat_1",
                "symbol": "BTC/USD",
                "asset_class": "CRYPTO",
                "side": "buy",
                "entry_fill_price": 50000.0,
                "exit_fill_price": 55000.0,
                "qty": 0.1,
                "entry_time": now.isoformat(),
                "exit_time": now.isoformat(),
                "exit_reason": "TP1",
                "realized_pnl_pct": 10.0,
                "realized_pnl_usd": 500.0,
                "entry_slippage_pct": 0.0,
            },
            {
                "position_id": "pos_old",
                "ds": old_time.date().isoformat(),
                "account_id": "paper",
                "strategy_id": "strat_1",
                "symbol": "ETH/USD",
                "asset_class": "CRYPTO",
                "side": "buy",
                "entry_fill_price": 3000.0,
                "exit_fill_price": 3300.0,
                "qty": 1.0,
                "entry_time": old_time.isoformat(),
                "exit_time": old_time.isoformat(),
                "exit_reason": "TP1",
                "realized_pnl_pct": 10.0,
                "realized_pnl_usd": 300.0,
                "entry_slippage_pct": 0.0,
            },
        ]

        # Mock Alpaca Activities Response
        # Page 1: Recent activity (for pos_recent) + noise
        # We need 'id' and 'activity_time' for pagination logic
        page1_last_id = "page1_end"
        page2_last_id = "page2_end"

        recent_time = now.isoformat()
        mid_time = (now - timedelta(days=2)).isoformat()
        old_time_str = old_time.isoformat()

        page1 = [
            {
                "id": "act1",
                "activity_time": recent_time,
                "activity_type": "CFEE",
                "order_id": "pos_recent",
                "qty": "5.00",
                "price": "1.0",
                "symbol": "USD",
            },
        ]
        # Fill with noise but ensure the last one has the ID we expect for pagination
        page1.extend(
            [
                {"id": f"noise_{i}", "activity_time": recent_time, "activity_type": "CSD"}
                for i in range(98)
            ]
        )
        page1.append(
            {"id": page1_last_id, "activity_time": mid_time, "activity_type": "CSD"}
        )

        # Page 2: Old activity (for pos_old)
        page2 = [
            {
                "id": "act_old",
                "activity_time": old_time_str,
                "activity_type": "CFEE",
                "order_id": "pos_old",
                "qty": "10.00",
                "price": "1.0",
                "symbol": "USD",
            },
            {"id": page2_last_id, "activity_time": old_time_str, "activity_type": "CSD"},
        ]

        # Mock separate orders to return correct IDs
        # get_order_by_client_id returns an object with .id attribute
        # This .id must match the activity's order_id

        mock_order_recent = MagicMock(
            id="pos_recent", filled_avg_price=50000.0, filled_qty=0.1
        )
        mock_order_old = MagicMock(id="pos_old", filled_avg_price=3000.0, filled_qty=1.0)

        def get_order_side_effect(client_id):
            if client_id == "pos_recent":
                return mock_order_recent
            if client_id == "pos_old":
                return mock_order_old
            return MagicMock()

        mock_alpaca.get_order_by_client_id.side_effect = get_order_side_effect

        # Mock Alpaca Activities Response
        # Page 1: Recent activity (for pos_recent) + noise
        # We need 'id' and 'activity_time' for pagination logic
        page1_last_id = "page1_end"
        page2_last_id = "page2_end"

        recent_time = now.isoformat()
        mid_time = (now - timedelta(days=2)).isoformat()
        old_time_str = old_time.isoformat()

        page1 = [
            {
                "id": "act1",
                "activity_time": recent_time,
                "activity_type": "CFEE",
                "order_id": "pos_recent",
                "qty": "5.00",
                "price": "1.0",
                "symbol": "USD",
            },
        ]
        # Fill with noise but ensure the last one has the ID we expect for pagination
        page1.extend(
            [
                {"id": f"noise_{i}", "activity_time": recent_time, "activity_type": "CSD"}
                for i in range(98)
            ]
        )
        page1.append(
            {"id": page1_last_id, "activity_time": mid_time, "activity_type": "CSD"}
        )

        # Page 2: Old activity (for pos_old)
        page2 = [
            {
                "id": "act_old",
                "activity_time": old_time_str,
                "activity_type": "CFEE",
                "order_id": "pos_old",
                "qty": "10.00",
                "price": "1.0",
                "symbol": "USD",
            },
            {"id": page2_last_id, "activity_time": old_time_str, "activity_type": "CSD"},
        ]

        # Mock the .get() call to return pages based on calls
        def side_effect(endpoint, params=None):
            if endpoint == "/account/activities":
                # If page_token is provided and matches page1's last ID, return page 2
                token = params.get("page_token") if params else None

                if token == page1_last_id:
                    return page2
                if not token:
                    return page1
                # Stop iteration for other tokens
                return []
            return []

        mock_alpaca.get.side_effect = side_effect

        pipeline = TradeArchivalPipeline()

        # Execute
        results = pipeline.transform(raw_data)

        # Verification
        # Schema uses 'trade_id', not 'position_id'

        # pos_recent should have fees (from page 1)
        recent_trade = next((t for t in results if t["trade_id"] == "pos_recent"), None)
        self.assertIsNotNone(recent_trade, "Result for pos_recent not found")
        self.assertEqual(recent_trade["actual_fee_usd"], 5.0)

        # pos_old should have fees (from page 2) - this proves pagination worked
        old_trade = next((t for t in results if t["trade_id"] == "pos_old"), None)
        self.assertIsNotNone(old_trade, "Result for pos_old not found")
        self.assertEqual(
            old_trade["actual_fee_usd"], 10.0, "Old trade should have fees from page 2"
        )
