import pytest
from unittest.mock import MagicMock, patch

from crypto_signals.domain.schemas import (
    AssetClass,
    OrderSide,
    Position,
    TradeType,
)
from crypto_signals.engine.execution import ExecutionEngine
from tests.factories import PositionFactory, SignalFactory


class TestExecutionGating:
    @pytest.fixture(autouse=True)
    def setup(self):
        # Mock settings (no spec to allow custom attributes)
        self.mock_settings = MagicMock()
        # Default to Paper Trading = True (so we only fail on ENVIRONMENT check)
        self.mock_settings.is_paper_trading = True
        self.mock_settings.ENABLE_EXECUTION = True
        self.mock_settings.RISK_PER_TRADE = 100.0
        self.mock_settings.TTL_DAYS_POSITION = 90
        self.mock_settings.MIN_ORDER_NOTIONAL_USD = 15.0

        # Mock Trading Client
        self.mock_client = MagicMock()

        # Patch get_settings to return our mock
        with patch(
            "crypto_signals.engine.execution.get_settings", return_value=self.mock_settings
        ), patch("crypto_signals.engine.execution.RiskEngine") as MockRiskEngine:
            # Configure RiskEngine instance to return passed=True
            from crypto_signals.engine.risk import RiskCheckResult

            MockRiskEngine.return_value.validate_signal.return_value = RiskCheckResult(
                passed=True
            )

            # Initialize engine with mocked client and repo
            self.mock_repo = MagicMock()
            self.engine = ExecutionEngine(
                trading_client=self.mock_client, repository=self.mock_repo
            )
            yield

    def test_gate_execute_signal_dev(self):
        """Test that execute_signal is BLOCKED in DEV environment."""
        # Arrange
        self.mock_settings.ENVIRONMENT = "DEV"

        signal = SignalFactory.build(
            symbol="BTC/USD",
            signal_id="test_sig",
            take_profit_1=50000,
            suggested_stop=40000,
            entry_price=45000,
            asset_class=AssetClass.CRYPTO,
            side=OrderSide.BUY,
        )

        # Act
        result = self.engine.execute_signal(signal)

        # Assert
        assert result is not None, "Expected result to be a position object"
        assert result.trade_type == "THEORETICAL", f"Expected THEORETICAL, got {result.trade_type}"
        # Should NOT call submit_order (broker)
        self.mock_client.submit_order.assert_not_called()

    def test_gate_execute_signal_prod(self):
        """Test that execute_signal is ALLOWED in PROD environment."""
        # Arrange
        self.mock_settings.ENVIRONMENT = "PROD"

        signal = SignalFactory.build(
            symbol="BTC/USD",
            signal_id="test_sig",
            take_profit_1=50000,
            suggested_stop=40000,
            entry_price=45000,
            asset_class=AssetClass.CRYPTO,
            side=OrderSide.BUY,
        )

        # Mock successful order
        mock_order = MagicMock()
        mock_order.id = "order_123"
        mock_order.status = "new"
        self.mock_client.submit_order.return_value = mock_order

        # Act
        result = self.engine.execute_signal(signal)

        # Assert
        assert isinstance(result, Position), "Expected result to be a Position instance"
        assert result.trade_type != "THEORETICAL", f"Expected non-theoretical, got {result.trade_type}"
        # Should call submit_order
        self.mock_client.submit_order.assert_called_once()

    def test_gate_sync_position_dev(self):
        """Test that sync_position skipped in DEV."""
        # Arrange
        self.mock_settings.ENVIRONMENT = "DEV"

        pos = PositionFactory.build(
            position_id="pos_1",
            alpaca_order_id="ord_1",
            trade_type=TradeType.THEORETICAL,
            symbol="BTC/USD",
            side=OrderSide.BUY,
        )

        # Act
        self.engine.sync_position_status(pos)

        # Assert
        self.mock_client.get_order_by_id.assert_not_called()

    def test_gate_modify_stop_dev(self):
        """Test that modify_stop_loss is skipped (simulated success) in DEV."""
        # Arrange
        self.mock_settings.ENVIRONMENT = "DEV"

        pos = PositionFactory.build(
            position_id="pos_1",
            trade_type=TradeType.THEORETICAL,
            symbol="BTC/USD",
            side=OrderSide.BUY,
        )

        # Act
        result = self.engine.modify_stop_loss(pos, 42000)

        # Assert
        assert result is True, "Expected True for modify_stop_loss in DEV"
        # Should NOT call replace_order
        self.mock_client.replace_order_by_id.assert_not_called()
