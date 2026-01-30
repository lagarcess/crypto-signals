from unittest.mock import MagicMock, patch
import pytest
from datetime import date
from crypto_signals.domain.schemas import AssetClass, OrderSide, Signal, SignalStatus
from crypto_signals.engine.execution import ExecutionEngine

class TestExecutionAccountID:

    def test_account_id_is_used_instead_of_hardcoded_string(self):
        """
        Verify that ExecutionEngine uses the real Alpaca Account UUID
        instead of hardcoded 'paper' or 'live' strings.
        """
        # Mock Settings to enable execution
        mock_settings = MagicMock()
        mock_settings.is_paper_trading = True
        mock_settings.ENABLE_EXECUTION = True
        mock_settings.ENVIRONMENT = "PROD"
        mock_settings.RISK_PER_TRADE = 100.0
        mock_settings.TTL_DAYS_POSITION = 90
        mock_settings.MIN_ORDER_NOTIONAL_USD = 10.0

        # Mock Trading Client
        mock_trading_client = MagicMock()

        # Mock Account with a specific UUID
        expected_account_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        mock_account = MagicMock()
        mock_account.id = expected_account_id
        mock_trading_client.get_account.return_value = mock_account

        # Mock Order submission response
        mock_order = MagicMock()
        mock_order.id = "test-order-id"
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Sample Signal
        signal = Signal(
            signal_id="test-signal-uuid",
            ds=date(2025, 1, 15),
            strategy_id="TEST",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="TEST",
            suggested_stop=48000.0,
            status=SignalStatus.WAITING,
            take_profit_1=55000.0,
            side=OrderSide.BUY,
        )

        with patch("crypto_signals.engine.execution.get_settings", return_value=mock_settings), \
             patch("crypto_signals.engine.execution.RiskEngine") as MockRiskEngine:

            # Configure RiskEngine to PASS
            mock_risk_instance = MockRiskEngine.return_value
            from crypto_signals.engine.risk import RiskCheckResult
            mock_risk_instance.validate_signal.return_value = RiskCheckResult(passed=True)

            # Initialize Engine
            engine = ExecutionEngine(
                trading_client=mock_trading_client,
                repository=MagicMock()
            )

            # Execute Signal
            position = engine.execute_signal(signal)

            # Verification
            assert position is not None
            assert position.account_id == expected_account_id, \
                f"Expected account_id {expected_account_id}, but got {position.account_id}"

    def test_account_id_defaults_to_unknown_on_api_error(self):
        """
        Verify that ExecutionEngine sets account_id to 'unknown' when
        fetching the account ID fails.
        """
        # Mock Settings
        mock_settings = MagicMock()
        mock_settings.ENVIRONMENT = "PROD"
        mock_settings.is_paper_trading = True

        # Mock Trading Client to raise exception
        mock_trading_client = MagicMock()
        mock_trading_client.get_account.side_effect = Exception("API Connection Failed")

        with patch("crypto_signals.engine.execution.get_settings", return_value=mock_settings), \
             patch("crypto_signals.engine.execution.RiskEngine"):

            # Initialize Engine
            engine = ExecutionEngine(
                trading_client=mock_trading_client,
                repository=MagicMock()
            )

            # Verify fallback
            assert engine.account_id == "unknown"
