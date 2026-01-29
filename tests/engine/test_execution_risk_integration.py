import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from crypto_signals.domain.schemas import (
    AssetClass,
    OrderSide,
    Signal,
    TradeStatus,
    TradeType,
)
from crypto_signals.engine.execution import ExecutionEngine
from crypto_signals.engine.risk import RiskCheckResult


class TestExecutionRiskIntegration(unittest.TestCase):
    def setUp(self):
        # Mock settings
        self.mock_settings = MagicMock()
        self.mock_settings.ENVIRONMENT = "PROD"  # Enable execution logic
        self.mock_settings.ENABLE_EXECUTION = True
        self.mock_settings.is_paper_trading = True
        self.mock_settings.RISK_PER_TRADE = 100.0
        self.mock_settings.TTL_DAYS_POSITION = 90
        self.mock_settings.MIN_ORDER_NOTIONAL_USD = 15.0

        # Patch settings
        self.settings_patcher = patch(
            "crypto_signals.engine.execution.get_settings",
            return_value=self.mock_settings,
        )
        self.settings_patcher.start()

        # Mock dependencies
        self.mock_client = MagicMock()
        self.mock_repo = MagicMock()

        # Initialize Engine with Mocks
        self.engine = ExecutionEngine(
            trading_client=self.mock_client, repository=self.mock_repo
        )

        # Mock RiskEngine (it's initialized inside __init__, so we improved dependency injection or patch it)
        # In our implementation we did: self.risk_engine = RiskEngine(...)
        # So we can simply replace the attribute on the instance
        self.mock_risk_engine = MagicMock()
        self.engine.risk_engine = self.mock_risk_engine

    def tearDown(self):
        self.settings_patcher.stop()

    def test_risk_block_creates_shadow_position(self):
        """Verify that a blocked trade returns a valid Position with RISK_BLOCKED type."""
        # 1. Setup Signal
        signal = MagicMock(spec=Signal)
        signal.symbol = "BTC/USD"
        signal.signal_id = "sig_risk_test"
        signal.entry_price = 50000.0
        signal.suggested_stop = 49000.0  # $1000 risk per share
        signal.take_profit_1 = 52000.0
        signal.asset_class = AssetClass.CRYPTO
        signal.ds = date(2023, 1, 1)
        signal.discord_thread_id = "12345"
        signal.side = OrderSide.BUY

        # 2. Setup Risk Rejection
        self.mock_risk_engine.validate_signal.return_value = RiskCheckResult(
            passed=False, reason="Max Sector Positions"
        )

        # 3. Execute
        position = self.engine.execute_signal(signal)

        # 4. Verify
        self.assertIsNotNone(position)
        self.assertEqual(position.trade_type, TradeType.RISK_BLOCKED.value)
        self.assertEqual(position.status, TradeStatus.CLOSED)
        self.assertIn("Max Sector Positions", position.failed_reason)

        # Verify Hydration (Synthesized Fields)
        # Risk = 100, Dist = 1000 -> Qty = 0.1
        self.assertAlmostEqual(position.qty, 0.1, places=2)
        self.assertEqual(position.entry_fill_price, 50000.0)
        self.assertEqual(position.account_id, "risk_blocked")

        # Make sure NO broker order was sent
        self.mock_client.submit_order.assert_not_called()

    def test_risk_pass_allows_execution(self):
        """Verify that passed risk check allows execution to proceed."""
        # Reduced test for pass-through
        signal = MagicMock(spec=Signal)
        # ... setup basics ...
        signal.symbol = "BTC/USD"
        signal.asset_class = AssetClass.CRYPTO
        signal.entry_price = 100
        signal.suggested_stop = 90
        signal.take_profit_1 = 110
        signal.side = OrderSide.BUY
        signal.signal_id = "sig_pass"
        signal.ds = date(2023, 1, 1)

        self.mock_risk_engine.validate_signal.return_value = RiskCheckResult(passed=True)

        # Execute
        self.engine.execute_signal(signal)

        # Verify call execution (for Crypto it calls submit_order)
        self.mock_client.submit_order.assert_called_once()
