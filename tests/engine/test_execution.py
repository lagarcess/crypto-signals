"""Unit tests for the ExecutionEngine module."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import (
    AssetClass,
    OrderSide,
    Signal,
    SignalStatus,
)
from crypto_signals.engine.execution import ExecutionEngine
from tests.factories import PositionFactory, SignalFactory


@pytest.fixture
def mock_settings():
    """Fixture for mocking settings."""
    mock = MagicMock()
    mock.is_paper_trading = True
    mock.ENABLE_EXECUTION = True
    mock.RISK_PER_TRADE = 100.0
    mock.ENVIRONMENT = "PROD"
    mock.TTL_DAYS_POSITION = 90
    mock.MIN_ORDER_NOTIONAL_USD = 15.0
    return mock


@pytest.fixture
def mock_trading_client():
    """Fixture for mocking TradingClient."""
    return MagicMock()


@pytest.fixture
def sample_signal():
    """Create a sample BUY signal for testing."""
    return SignalFactory.build(
        signal_id="test-signal-123",
        ds=date(2025, 1, 15),
        strategy_id="BULLISH_ENGULFING",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=50000.0,
        pattern_name="BULLISH_ENGULFING",
        suggested_stop=48000.0,
        status=SignalStatus.WAITING,
        take_profit_1=55000.0,
        take_profit_2=60000.0,
        side=OrderSide.BUY,
    )


@pytest.fixture
def sample_sell_signal():
    """Create a sample SELL signal for testing short positions."""
    return SignalFactory.build(
        signal_id="test-signal-sell-456",
        ds=date(2025, 1, 15),
        strategy_id="BEARISH_ENGULFING",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        entry_price=50000.0,
        pattern_name="BEARISH_ENGULFING",
        suggested_stop=52000.0,  # Stop ABOVE entry for short
        status=SignalStatus.WAITING,
        take_profit_1=45000.0,  # TP BELOW entry for short
        take_profit_2=40000.0,
        side=OrderSide.SELL,
    )


@pytest.fixture
def sample_equity_signal():
    """Create a sample equity BUY signal for testing bracket orders.

    Bracket orders (OTOCO) are only supported for equities, not crypto.
    """
    return SignalFactory.build(
        signal_id="test-signal-equity-789",
        ds=date(2025, 1, 15),
        strategy_id="BULLISH_ENGULFING",
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
        entry_price=150.0,
        pattern_name="BULLISH_ENGULFING",
        suggested_stop=145.0,
        status=SignalStatus.WAITING,
        take_profit_1=160.0,
        take_profit_2=170.0,
        side=OrderSide.BUY,
    )


@pytest.fixture
def execution_engine(mock_settings, mock_trading_client):
    """Create an ExecutionEngine with mocked dependencies."""
    with (
        patch("crypto_signals.engine.execution.get_settings", return_value=mock_settings),
        patch("crypto_signals.engine.execution.RiskEngine") as MockRiskEngine,
    ):
        # Configure default RiskEngine behavior to Pass
        mock_risk_instance = MockRiskEngine.return_value
        from crypto_signals.engine.risk import RiskCheckResult

        mock_risk_instance.validate_signal.return_value = RiskCheckResult(passed=True)

        # Mock Repository to avoid Firestore Auth
        mock_repo = MagicMock()
        engine = ExecutionEngine(trading_client=mock_trading_client, repository=mock_repo)
        yield engine


class TestExecuteSignal:
    """Tests for the execute_signal method."""

    def test_bracket_order_construction(
        self, execution_engine, sample_equity_signal, mock_trading_client
    ):
        """Verify MarketOrderRequest is constructed with OrderClass.BRACKET for equity."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_equity_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        position = execution_engine.execute_signal(sample_equity_signal)

        # Assert
        assert position is not None, "Execution failed to return a position object"
        mock_trading_client.submit_order.assert_called_once()

        # Get the order request that was passed
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]  # First positional argument

        # Verify bracket order class
        from alpaca.trading.enums import OrderClass

        assert (
            order_request.order_class == OrderClass.BRACKET
        ), f"Expected BRACKET order class, got {order_request.order_class}"

    def test_take_profit_matches_signal(
        self, execution_engine, sample_equity_signal, mock_trading_client
    ):
        """Verify take_profit param matches signal's take_profit_1 for equity bracket orders."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_equity_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        execution_engine.execute_signal(sample_equity_signal)

        # Assert
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]
        expected_tp = round(sample_equity_signal.take_profit_1, 2)
        assert (
            order_request.take_profit.limit_price == expected_tp
        ), f"Expected take profit {expected_tp}, but got {order_request.take_profit.limit_price}"

    def test_stop_loss_matches_signal(
        self, execution_engine, sample_equity_signal, mock_trading_client
    ):
        """Verify stop_loss param matches signal's suggested_stop for equity bracket orders."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_equity_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        execution_engine.execute_signal(sample_equity_signal)

        # Assert
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]
        expected_stop = round(sample_equity_signal.suggested_stop, 2)
        assert (
            order_request.stop_loss.stop_price == expected_stop
        ), f"Expected stop loss {expected_stop}, but got {order_request.stop_loss.stop_price}"

    def test_client_order_id_matches_signal_id(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify client_order_id equals signal.signal_id for traceability."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        execution_engine.execute_signal(sample_signal)

        # Assert
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]
        assert (
            order_request.client_order_id == sample_signal.signal_id
        ), f"Expected client_order_id {sample_signal.signal_id}, but got {order_request.client_order_id}"

    def test_qty_calculation(self, execution_engine, sample_signal, mock_trading_client):
        """Verify qty calculation based on risk per trade and distance to stop."""
        # Arrange - RISK_PER_TRADE = 100, entry = 50000, stop = 48000
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        execution_engine.execute_signal(sample_signal)

        # Assert
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]
        # Risk per share = 50000 - 48000 = 2000. Expected qty = 100 / 2000 = 0.05
        expected_qty = round(100.0 / 2000.0, 6)
        assert (
            order_request.qty == expected_qty
        ), f"Quantity mismatch. Expected {expected_qty}, got {order_request.qty}"

    def test_execution_blocked_when_not_paper_trading(
        self, sample_signal, mock_trading_client
    ):
        """Verify execution is blocked when ALPACA_PAPER_TRADING=False."""
        # Arrange
        mock_settings = MagicMock()
        mock_settings.is_paper_trading = False
        mock_settings.ENABLE_EXECUTION = True
        mock_settings.TTL_DAYS_POSITION = 90
        mock_settings.ENVIRONMENT = "PROD"
        mock_settings.RISK_PER_TRADE = 100.0

        with (
            patch(
                "crypto_signals.engine.execution.get_settings", return_value=mock_settings
            ),
            patch("crypto_signals.engine.execution.RiskEngine") as MockRiskEngine,
        ):
            MockRiskEngine.return_value.validate_signal.return_value.passed = True
            mock_repo = MagicMock()
            engine = ExecutionEngine(
                trading_client=mock_trading_client, repository=mock_repo
            )

            # Act
            position = engine.execute_signal(sample_signal)

            # Assert
            mock_trading_client.submit_order.assert_not_called()
            assert position is not None, "Execution failed to return a position object"
            assert (
                position.trade_type == "THEORETICAL"
            ), f"Expected THEORETICAL trade type, got {position.trade_type}"

    def test_execution_blocked_when_disabled(self, sample_signal, mock_trading_client):
        """Verify execution is blocked when ENABLE_EXECUTION=False."""
        # Arrange
        mock_settings = MagicMock()
        mock_settings.is_paper_trading = True
        mock_settings.ENABLE_EXECUTION = False
        mock_settings.ENVIRONMENT = "PROD"
        mock_settings.RISK_PER_TRADE = 100.0
        mock_settings.TTL_DAYS_POSITION = 90

        with (
            patch(
                "crypto_signals.engine.execution.get_settings", return_value=mock_settings
            ),
            patch("crypto_signals.engine.execution.RiskEngine") as MockRiskEngine,
        ):
            MockRiskEngine.return_value.validate_signal.return_value.passed = True
            mock_repo = MagicMock()
            engine = ExecutionEngine(
                trading_client=mock_trading_client, repository=mock_repo
            )

            # Act
            position = engine.execute_signal(sample_signal)

            # Assert
            mock_trading_client.submit_order.assert_not_called()
            assert position is not None, "Execution failed to return a position object"
            assert (
                position.trade_type == "THEORETICAL"
            ), f"Expected THEORETICAL trade type, got {position.trade_type}"

    def test_position_created_on_success(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify Position object is created with correct fields on success."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        position = execution_engine.execute_signal(sample_signal)

        # Assert
        assert position is not None, "Execution failed to return a position object"
        assert (
            position.position_id == sample_signal.signal_id
        ), f"Expected position_id {sample_signal.signal_id} but got {position.position_id}"
        assert (
            position.delete_at is not None
        ), "delete_at timestamp should be set in position"
        assert (
            position.signal_id == sample_signal.signal_id
        ), f"Expected signal_id {sample_signal.signal_id} but got {position.signal_id}"
        assert (
            position.current_stop_loss == sample_signal.suggested_stop
        ), f"Expected stop loss {sample_signal.suggested_stop} but got {position.current_stop_loss}"
        assert (
            position.entry_fill_price == sample_signal.entry_price
        ), f"Expected entry price {sample_signal.entry_price} but got {position.entry_fill_price}"
        assert (
            position.side == sample_signal.side
        ), f"Expected side {sample_signal.side} but got {position.side}"

    def test_sell_order_side(
        self, execution_engine, sample_sell_signal, mock_trading_client
    ):
        """Verify SELL signals submit orders with OrderSide.SELL."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-sell-789"
        mock_order.client_order_id = sample_sell_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        position = execution_engine.execute_signal(sample_sell_signal)

        # Assert
        assert position is not None, "Execution failed to return a position object"
        mock_trading_client.submit_order.assert_called_once()

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify SELL order side
        from alpaca.trading.enums import OrderSide as AlpacaOrderSide

        assert (
            order_request.side == AlpacaOrderSide.SELL
        ), f"Expected SELL order request side but got {order_request.side}"
        assert (
            position.side == OrderSide.SELL
        ), f"Expected position side SELL but got {position.side}"


class TestCryptoOrderFlow:
    """Tests for crypto-specific order flow (simple market orders, no bracket)."""

    def test_crypto_uses_simple_market_order(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify crypto orders do NOT include order_class (no bracket)."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        position = execution_engine.execute_signal(sample_signal)

        # Assert
        assert position is not None, "Execution should return a position"
        mock_trading_client.submit_order.assert_called_once()
        order_request = mock_trading_client.submit_order.call_args[0][0]
        assert (
            order_request.order_class is None
        ), f"Expected order_class to be None for crypto, but got {order_request.order_class}"

    def test_crypto_uses_gtc_time_in_force(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify crypto orders use GTC time_in_force (required by Alpaca)."""
        from alpaca.trading.enums import TimeInForce

        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-gtc"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        execution_engine.execute_signal(sample_signal)

        # Assert
        order_request = mock_trading_client.submit_order.call_args[0][0]
        assert (
            order_request.time_in_force == TimeInForce.GTC
        ), f"Expected GTC time_in_force, but got {order_request.time_in_force}"

    def test_crypto_position_has_manual_sl_tp_fields(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify Position stores SL/TP for manual exit tracking."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-sltp"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        position = execution_engine.execute_signal(sample_signal)

        # Assert
        assert position is not None, "Execution failed to return a position object"
        assert (
            position.current_stop_loss == sample_signal.suggested_stop
        ), f"Expected stop loss {sample_signal.suggested_stop}, but got {position.current_stop_loss}"
        assert (
            position.tp_order_id is None
        ), "Crypto position should not have tp_order_id initially"
        assert (
            position.sl_order_id is None
        ), "Crypto position should not have sl_order_id initially"

    def test_crypto_no_take_profit_in_order(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify crypto orders do NOT include take_profit parameter."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-notp"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        execution_engine.execute_signal(sample_signal)

        # Assert
        order_request = mock_trading_client.submit_order.call_args[0][0]
        assert (
            not hasattr(order_request, "take_profit") or order_request.take_profit is None
        ), "Crypto order request should not have take_profit set"

    def test_crypto_no_stop_loss_in_order(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify crypto orders do NOT include stop_loss parameter."""
        # Arrange
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-nosl"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Act
        execution_engine.execute_signal(sample_signal)

        # Assert
        order_request = mock_trading_client.submit_order.call_args[0][0]
        assert (
            not hasattr(order_request, "stop_loss") or order_request.stop_loss is None
        ), "Crypto order request should not have stop_loss set"


class TestValidateSignal:
    """Tests for signal validation."""

    @pytest.mark.parametrize(
        "overrides, expected_result, message",
        [
            ({"take_profit_1": None}, False, "Validation should fail when take_profit_1 is missing"),
            ({"suggested_stop": 0}, False, "Validation should fail when suggested_stop is 0"),
            ({"suggested_stop": -100.0}, False, "Validation should fail when suggested_stop is negative"),
        ],
    )
    def test_validate_signal_failures(self, execution_engine, overrides, expected_result, message):
        """Verify that validation fails for various invalid signal parameters."""
        # Arrange
        signal = SignalFactory.build(**overrides)

        # Act
        result = execution_engine._validate_signal(signal)

        # Assert
        assert result == expected_result, message


class TestCalculateQty:
    """Tests for position size calculation."""

    def test_crypto_fractional_shares(self, execution_engine, sample_signal):
        """Verify crypto allows fractional shares with 6 decimals."""
        # sample_signal: entry=50000, stop=48000, risk_distance=2000
        qty = execution_engine._calculate_qty(sample_signal)

        # Crypto should be rounded to 6 decimals: 100 / 2000 = 0.05
        assert qty == round(100.0 / 2000.0, 6), "Qty calculation incorrect for crypto"

    def test_equity_fractional_shares(self, execution_engine):
        """Verify equity uses 4 decimal precision."""
        # Arrange
        signal = SignalFactory.build(
            signal_id="test-signal",
            ds=date(2025, 1, 15),
            strategy_id="TEST",
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            entry_price=150.0,
            pattern_name="TEST",
            suggested_stop=145.0,
            take_profit_1=160.0,
        )

        # Act
        qty = execution_engine._calculate_qty(signal)

        # Assert
        # Equity should be rounded to 4 decimals: 100 / (150 - 145) = 20
        expected_qty = round(100.0 / 5.0, 4)
        assert qty == expected_qty, f"Expected equity qty {expected_qty}, but got {qty}"


class TestErrorHandling:
    """Tests for error handling and Rich error panels."""

    def test_api_failure_returns_none(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify API failure returns None and doesn't raise."""
        # Setup - simulate Alpaca API failure
        mock_trading_client.submit_order.side_effect = Exception(
            "Insufficient buying power"
        )

        # Execute - should not raise
        position = execution_engine.execute_signal(sample_signal)

        # Verify
        assert position is None, "Position should be None on API failure"


class TestGetOrderDetails:
    """Tests for the get_order_details method."""

    def test_get_order_details_success(self, execution_engine, mock_trading_client):
        """Verify successful order retrieval."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "order-123"
        mock_order.status = "filled"
        mock_trading_client.get_order_by_id.return_value = mock_order

        # Execute
        order = execution_engine.get_order_details("order-123")

        # Verify
        assert order is not None, "get_order_details returned None for existing order"
        assert order.status == "filled", "Order status mismatch"
        mock_trading_client.get_order_by_id.assert_called_once_with("order-123")

    def test_get_order_details_not_found(self, execution_engine, mock_trading_client):
        """Verify returns None when order not found."""
        # Setup
        mock_trading_client.get_order_by_id.side_effect = Exception("Order not found")

        # Execute
        order = execution_engine.get_order_details("nonexistent-order")

        # Verify
        assert order is None, "get_order_details should return None for nonexistent order"


class TestSyncPositionStatus:
    """Tests for the sync_position_status method."""

    def test_sync_extracts_leg_ids(self, execution_engine, mock_trading_client):
        """Verify TP and SL leg IDs are extracted from filled parent order."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_tp_leg = MagicMock()
        mock_tp_leg.id = "tp-leg-uuid-123"
        mock_tp_leg.order_type = "limit"
        mock_tp_leg.status = "new"

        mock_sl_leg = MagicMock()
        mock_sl_leg.id = "sl-leg-uuid-456"
        mock_sl_leg.order_type = "stop"
        mock_sl_leg.status = "new"

        mock_order = MagicMock()
        mock_order.id = "parent-order-123"
        mock_order.status = "filled"
        # Use real datetime objects, not strings, as expected by calculation logic
        from datetime import datetime, timezone

        mock_order.filled_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        mock_order.filled_avg_price = "50100.0"
        mock_order.legs = [mock_tp_leg, mock_sl_leg]

        mock_trading_client.get_order_by_id.return_value = mock_order

        position = PositionFactory.build(
            position_id="test-pos-1",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-1",
            alpaca_order_id="parent-order-123",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        # Act
        updated = execution_engine.sync_position_status(position)

        # Assert
        assert updated.tp_order_id == "tp-leg-uuid-123", f"Expected TP order ID tp-leg-uuid-123, but got {updated.tp_order_id}"
        assert updated.sl_order_id == "sl-leg-uuid-456", f"Expected SL order ID sl-leg-uuid-456, but got {updated.sl_order_id}"
        assert updated.entry_fill_price == 50100.0, f"Expected entry fill price 50100.0, but got {updated.entry_fill_price}"

    def test_sync_detects_external_close_via_tp(
        self, execution_engine, mock_trading_client
    ):
        """Verify position marked CLOSED when TP order is filled."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_parent = MagicMock()
        mock_parent.status = "filled"
        mock_parent.filled_at = None
        mock_parent.filled_avg_price = None
        mock_parent.legs = []

        mock_tp_order = MagicMock()
        mock_tp_order.status = "filled"

        def side_effect(order_id):
            if order_id == "parent-id":
                return mock_parent
            elif order_id == "tp-order-id":
                return mock_tp_order
            return None

        mock_trading_client.get_order_by_id.side_effect = side_effect

        position = PositionFactory.build(
            position_id="test-pos-2",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-2",
            alpaca_order_id="parent-id",
            tp_order_id="tp-order-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        # Act
        updated = execution_engine.sync_position_status(position)

        # Assert
        assert (
            updated.status == TradeStatus.CLOSED
        ), f"Expected position status CLOSED, but got {updated.status}"

    def test_sync_captures_exit_fill_price_on_tp_fill(
        self, execution_engine, mock_trading_client
    ):
        """Verify exit_fill_price is captured when TP order is filled."""
        from datetime import datetime, timezone

        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_parent = MagicMock()
        mock_parent.status = "filled"
        mock_parent.filled_at = None
        mock_parent.filled_avg_price = None
        mock_parent.legs = []

        mock_tp_order = MagicMock()
        mock_tp_order.status = "filled"
        mock_tp_order.filled_avg_price = "55000.0"
        exit_time = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        mock_tp_order.filled_at = exit_time

        def side_effect(order_id):
            if order_id == "parent-id":
                return mock_parent
            elif order_id == "tp-order-id":
                return mock_tp_order
            return None

        mock_trading_client.get_order_by_id.side_effect = side_effect

        position = PositionFactory.build(
            position_id="test-pos-exit",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-exit",
            alpaca_order_id="parent-id",
            tp_order_id="tp-order-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        # Act
        updated = execution_engine.sync_position_status(position)

        # Assert
        assert (
            updated.status == TradeStatus.CLOSED
        ), f"Expected position status CLOSED, but got {updated.status}"
        assert updated.exit_fill_price == 55000.0, f"Expected exit price 55000.0, but got {updated.exit_fill_price}"
        assert updated.exit_time == exit_time, f"Expected exit time {exit_time}, but got {updated.exit_time}"

    def test_sync_captures_exit_details_on_sl_fill(
        self, execution_engine, mock_trading_client
    ):
        """Verify exit_fill_price is captured when SL order is filled."""
        from datetime import datetime, timezone

        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_parent = MagicMock()
        mock_parent.status = "filled"
        mock_parent.filled_at = None
        mock_parent.filled_avg_price = None
        mock_parent.legs = []

        mock_tp_order = MagicMock()
        mock_tp_order.status = "new"  # TP not filled

        mock_sl_order = MagicMock()
        mock_sl_order.status = "filled"
        mock_sl_order.filled_avg_price = "48000.0"
        exit_time = datetime(2025, 1, 15, 16, 0, 0, tzinfo=timezone.utc)
        mock_sl_order.filled_at = exit_time

        def side_effect(order_id):
            if order_id == "parent-id":
                return mock_parent
            elif order_id == "tp-order-id":
                return mock_tp_order
            elif order_id == "sl-order-id":
                return mock_sl_order
            return None

        mock_trading_client.get_order_by_id.side_effect = side_effect

        position = PositionFactory.build(
            position_id="test-pos-sl-exit",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-sl-exit",
            alpaca_order_id="parent-id",
            tp_order_id="tp-order-id",
            sl_order_id="sl-order-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        # Act
        updated = execution_engine.sync_position_status(position)

        # Assert
        assert (
            updated.status == TradeStatus.CLOSED
        ), f"Expected position status CLOSED, but got {updated.status}"
        assert updated.exit_fill_price == 48000.0, f"Expected exit price 48000.0, but got {updated.exit_fill_price}"
        assert updated.exit_time == exit_time, f"Expected exit time {exit_time}, but got {updated.exit_time}"

    def test_sync_detects_manual_exit_when_not_found(
        self, execution_engine, mock_trading_client
    ):
        """Verify position marked CLOSED (Manual Exit) when not found on Alpaca."""
        from datetime import datetime, timezone

        from crypto_signals.domain.schemas import ExitReason, TradeStatus

        # Arrange
        mock_parent = MagicMock()
        mock_parent.status = "filled"
        mock_parent.legs = []

        mock_trading_client.get_open_position.side_effect = Exception(
            "position not found (404)"
        )

        mock_close_order = MagicMock()
        mock_close_order.id = "manual-close-id"
        mock_close_order.status = "filled"
        mock_close_order.filled_avg_price = "52000.0"
        exit_time = datetime(2025, 1, 15, 17, 0, 0, tzinfo=timezone.utc)
        mock_close_order.filled_at = exit_time

        mock_trading_client.get_orders.return_value = [mock_close_order]
        mock_trading_client.get_order_by_id.return_value = mock_parent

        position = PositionFactory.build(
            position_id="test-pos-manual",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-manual",
            alpaca_order_id="parent-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        mock_reconciler = MagicMock()

        def mock_handle(p):
            p.status = TradeStatus.CLOSED
            p.exit_reason = ExitReason.MANUAL_EXIT
            p.exit_fill_price = 52000.0
            p.exit_time = exit_time
            return True

        mock_reconciler.handle_manual_exit_verification.side_effect = mock_handle
        execution_engine.reconciler = mock_reconciler

        # Act
        updated = execution_engine.sync_position_status(position)

        # Assert
        assert (
            updated.status == TradeStatus.CLOSED
        ), f"Expected position status CLOSED, but got {updated.status}"
        assert (
            updated.exit_reason == ExitReason.MANUAL_EXIT
        ), f"Expected exit reason MANUAL_EXIT, but got {updated.exit_reason}"
        assert updated.exit_fill_price == 52000.0, f"Expected exit price 52000.0, but got {updated.exit_fill_price}"
        assert updated.exit_time == exit_time, f"Expected exit time {exit_time}, but got {updated.exit_time}"
        mock_reconciler.handle_manual_exit_verification.assert_called_once_with(position)


class TestModifyStopLoss:
    """Tests for the modify_stop_loss method."""

    def test_modify_stop_loss_success(self, execution_engine, mock_trading_client):
        """Verify stop loss can be replaced when in replaceable state."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"

        mock_replaced_order = MagicMock()
        mock_replaced_order.id = "new-sl-order-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced_order

        position = PositionFactory.build(
            position_id="test-pos-3",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-3",
            alpaca_order_id="parent-id",
            sl_order_id="old-sl-order-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        # Act
        result = execution_engine.modify_stop_loss(position, 49000.0)

        # Assert
        assert result is True, "modify_stop_loss should return True on success"
        assert position.sl_order_id == "new-sl-order-id", f"Expected SL order ID new-sl-order-id, but got {position.sl_order_id}"
        assert position.current_stop_loss == 49000.0, f"Expected current_stop_loss 49000.0, but got {position.current_stop_loss}"
        mock_trading_client.replace_order_by_id.assert_called_once()

    def test_modify_stop_loss_pending_fails(self, execution_engine, mock_trading_client):
        """Verify replacement fails when order is in pending state."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_sl_order = MagicMock()
        mock_sl_order.status = "pending_replace"
        mock_trading_client.get_order_by_id.return_value = mock_sl_order

        position = PositionFactory.build(
            position_id="test-pos-4",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-4",
            alpaca_order_id="parent-id",
            sl_order_id="sl-order-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        # Act
        result = execution_engine.modify_stop_loss(position, 49000.0)

        # Assert
        assert result is False, "modify_stop_loss should fail for pending order"
        mock_trading_client.replace_order_by_id.assert_not_called()


class TestClosePositionEmergency:
    """Tests for the close_position_emergency method."""

    def test_emergency_close_cancels_all_legs(
        self, execution_engine, mock_trading_client
    ):
        """Verify all legs are canceled and market close order submitted."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_close_order = MagicMock()
        mock_close_order.id = "close-order-id"
        mock_trading_client.submit_order.return_value = mock_close_order

        mock_parent_order = MagicMock()
        mock_parent_order.symbol = "BTC/USD"
        mock_trading_client.get_order_by_id.return_value = mock_parent_order

        position = PositionFactory.build(
            position_id="test-pos-5",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-5",
            alpaca_order_id="parent-id",
            tp_order_id="tp-order-id",
            sl_order_id="sl-order-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        # Act
        result = execution_engine.close_position_emergency(position)

        # Assert
        assert result is True, "close_position_emergency failed to return True"
        assert (
            position.status == TradeStatus.CLOSED
        ), f"Expected position status CLOSED, but got {position.status}"

        # Verify cancel calls for TP and SL
        cancel_calls = mock_trading_client.cancel_order_by_id.call_args_list
        canceled_ids = [call[0][0] for call in cancel_calls]
        assert "tp-order-id" in canceled_ids, f"TP order tp-order-id not found in {canceled_ids}"
        assert "sl-order-id" in canceled_ids, f"SL order sl-order-id not found in {canceled_ids}"

        # Verify market close order submitted
        mock_trading_client.submit_order.assert_called_once()


class TestScaleOutPosition:
    """Tests for the scale_out_position method."""

    def test_scale_out_calculates_correct_qty(
        self, execution_engine, mock_trading_client
    ):
        """Verify 50% scale-out calculates the correct quantity."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_close_order = MagicMock()
        mock_close_order.id = "scale-order-123"
        mock_close_order.filled_avg_price = "55000.0"
        mock_trading_client.submit_order.return_value = mock_close_order

        position = PositionFactory.build(
            position_id="test-scale-1",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-scale",
            alpaca_order_id="parent-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.10,
            side=OrderSide.BUY,
        )

        # Act
        result = execution_engine.scale_out_position(position, scale_pct=0.5)

        # Assert
        assert result is True, "scale_out_position failed to return True"
        call_args = mock_trading_client.submit_order.call_args[0][0]
        assert (
            call_args.qty == 0.05
        ), f"Scale out qty mismatch. Expected 0.05, got {call_args.qty}"

    def test_scale_out_updates_remaining_qty(self, execution_engine, mock_trading_client):
        """Verify position.qty is reduced after scale-out."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_close_order = MagicMock()
        mock_close_order.id = "scale-order-123"
        mock_close_order.filled_avg_price = "55000.0"
        mock_trading_client.submit_order.return_value = mock_close_order

        position = PositionFactory.build(
            position_id="test-scale-2",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-scale",
            alpaca_order_id="parent-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.10,
            side=OrderSide.BUY,
        )

        # Act
        execution_engine.scale_out_position(position, scale_pct=0.5)

        # Assert
        assert (
            position.qty == 0.05
        ), f"Remaining qty mismatch. Expected 0.05, got {position.qty}"

    def test_scale_out_captures_original_qty_once(
        self, execution_engine, mock_trading_client
    ):
        """Verify original_qty is set only on first scale-out, not overwritten."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_close_order = MagicMock()
        mock_close_order.id = "scale-order-123"
        mock_close_order.filled_avg_price = "55000.0"
        mock_trading_client.submit_order.return_value = mock_close_order

        position = PositionFactory.build(
            position_id="test-scale-orig",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-scale",
            alpaca_order_id="parent-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=1.0,  # Start with 1.0
            side=OrderSide.BUY,
        )

        # Act
        # First scale-out (50%): 1.0 -> 0.5
        execution_engine.scale_out_position(position, scale_pct=0.5)
        # Second scale-out (50% of remaining): 0.5 -> 0.25
        execution_engine.scale_out_position(position, scale_pct=0.5)

        # Assert
        assert (
            position.original_qty == 1.0
        ), f"Expected original_qty 1.0, but got {position.original_qty}"

    def test_scale_out_appends_to_prices_list(
        self, execution_engine, mock_trading_client
    ):
        """Verify scaled_out_prices list accumulates for multi-stage exits."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        # First scale-out at $55,000
        mock_order_1 = MagicMock()
        mock_order_1.id = "scale-order-1"
        mock_order_1.filled_avg_price = "55000.0"

        # Second scale-out at $58,000
        mock_order_2 = MagicMock()
        mock_order_2.id = "scale-order-2"
        mock_order_2.filled_avg_price = "58000.0"

        mock_trading_client.submit_order.side_effect = [mock_order_1, mock_order_2]

        position = PositionFactory.build(
            position_id="test-scale-prices",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-scale",
            alpaca_order_id="parent-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=1.0,
            side=OrderSide.BUY,
        )

        # Act
        # First scale-out
        execution_engine.scale_out_position(position, scale_pct=0.5)
        # Second scale-out
        execution_engine.scale_out_position(position, scale_pct=0.5)

        # Assert
        assert (
            len(position.scaled_out_prices) == 2
        ), f"Expected 2 scaled out prices, but got {len(position.scaled_out_prices)}"
        assert (
            position.scaled_out_prices[0]["price"] == 55000.0
        ), f"First scale out price mismatch: {position.scaled_out_prices[0]['price']}"
        assert position.scaled_out_prices[0]["qty"] == 0.5, "First scale out qty mismatch"
        assert (
            position.scaled_out_prices[1]["price"] == 58000.0
        ), f"Second scale out price mismatch: {position.scaled_out_prices[1]['price']}"
        assert (
            position.scaled_out_prices[1]["qty"] == 0.25
        ), "Second scale out qty mismatch"

    def test_scale_out_fails_with_no_qty(self, execution_engine, mock_trading_client):
        """Verify scale_out_position returns False when position has no quantity."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        position = PositionFactory.build(
            position_id="test-scale-zero",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-scale",
            alpaca_order_id="parent-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0,  # Zero qty!
            side=OrderSide.BUY,
        )

        # Act
        result = execution_engine.scale_out_position(position, scale_pct=0.5)

        # Assert
        assert result is False, "scale_out_position should fail for zero qty"
        mock_trading_client.submit_order.assert_not_called()

    def test_scale_out_handles_order_failure(self, execution_engine, mock_trading_client):
        """Verify failed_reason is set when order submission fails during scale-out."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_trading_client.submit_order.side_effect = Exception("Insufficient funds")

        position = PositionFactory.build(
            position_id="test-scale-fail",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-scale",
            alpaca_order_id="parent-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.10,
            side=OrderSide.BUY,
        )

        # Act
        result = execution_engine.scale_out_position(position, scale_pct=0.5)

        # Assert
        assert result is False, "scale_out_position should fail on API exception"
        assert (
            "Scale-out failed" in position.failed_reason
        ), f"Expected 'Scale-out failed' in failed_reason, but got {position.failed_reason}"


class TestMoveStopToBreakeven:
    """Tests for the move_stop_to_breakeven method."""

    def test_breakeven_moves_stop_to_entry(self, execution_engine, mock_trading_client):
        """Verify stop is moved to entry price (with buffer)."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"

        mock_replaced_order = MagicMock()
        mock_replaced_order.id = "new-sl-order-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced_order

        position = PositionFactory.build(
            position_id="test-breakeven-1",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-be",
            alpaca_order_id="parent-id",
            sl_order_id="old-sl-order-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        # Act
        result = execution_engine.move_stop_to_breakeven(position)

        # Assert
        assert result is True, "move_stop_to_breakeven failed to return True"
        # Entry + 0.1% buffer = 50000 * 1.001 = 50050
        assert (
            position.current_stop_loss == 50050.0
        ), f"Expected stop loss 50050.0, but got {position.current_stop_loss}"

    def test_breakeven_applies_buffer_for_longs(
        self, execution_engine, mock_trading_client
    ):
        """Verify 0.1% buffer is above entry for long positions."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"
        mock_replaced = MagicMock()
        mock_replaced.id = "new-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced

        position = PositionFactory.build(
            position_id="test-be-long",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-be",
            alpaca_order_id="parent-id",
            sl_order_id="sl-id",
            status=TradeStatus.OPEN,
            entry_fill_price=100.0,
            current_stop_loss=95.0,
            qty=1.0,
            side=OrderSide.BUY,
        )

        # Act
        execution_engine.move_stop_to_breakeven(position)

        # Assert
        # Long: 100 * 1.001 = 100.10, rounded to 100.1
        assert (
            position.current_stop_loss == 100.1
        ), f"Expected stop loss 100.1 for long, but got {position.current_stop_loss}"

    def test_breakeven_applies_buffer_for_shorts(
        self, execution_engine, mock_trading_client
    ):
        """Verify 0.1% buffer is below entry for short positions."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"
        mock_replaced = MagicMock()
        mock_replaced.id = "new-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced

        position = PositionFactory.build(
            position_id="test-be-short",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-be",
            alpaca_order_id="parent-id",
            sl_order_id="sl-id",
            status=TradeStatus.OPEN,
            entry_fill_price=100.0,
            current_stop_loss=105.0,
            qty=1.0,
            side=OrderSide.SELL,  # Short position
        )

        # Act
        execution_engine.move_stop_to_breakeven(position)

        # Assert
        # Short: 100 * 0.999 = 99.90, rounded to 99.9
        assert (
            position.current_stop_loss == 99.9
        ), f"Expected stop loss 99.9 for short, but got {position.current_stop_loss}"

    def test_breakeven_sets_flag(self, execution_engine, mock_trading_client):
        """Verify breakeven_applied flag is set to True on success."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"
        mock_replaced = MagicMock()
        mock_replaced.id = "new-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced

        position = PositionFactory.build(
            position_id="test-be-flag",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-be",
            alpaca_order_id="parent-id",
            sl_order_id="sl-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )

        assert (
            position.breakeven_applied is False
        ), "breakeven_applied should be False initially"

        # Act
        execution_engine.move_stop_to_breakeven(position)

        # Assert
        assert (
            position.breakeven_applied is True
        ), "breakeven_applied should be True after success"

    def test_breakeven_fails_without_entry_price(
        self, execution_engine, mock_trading_client
    ):
        """Verify move_stop_to_breakeven returns False when entry_fill_price is missing."""
        from crypto_signals.domain.schemas import TradeStatus

        # Arrange
        position = PositionFactory.build(
            position_id="test-be-no-entry",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-be",
            alpaca_order_id="parent-id",
            sl_order_id="sl-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )
        position.entry_fill_price = None

        # Act
        result = execution_engine.move_stop_to_breakeven(position)

        # Assert
        assert result is False, "move_stop_to_breakeven should fail without entry price"
        mock_trading_client.replace_order_by_id.assert_not_called()


class TestCFEEReconciliation:
    """Tests for CFEE (Crypto Fee) reconciliation methods (Issue #140)."""

    def test_get_crypto_fees_by_orders_success(
        self, execution_engine, mock_trading_client
    ):
        """Verify successful CFEE fetching and currency normalization."""
        # Setup mock CFEE activity (as dict for raw GET)
        mock_activity = {
            "id": "cfee-123",
            "symbol": "BTCUSD",
            "qty": "-0.0001",
            "price": "50000.0",
            "date": "2025-01-16",
            "description": "Tier 0: 0.25%",
        }

        mock_trading_client.get.return_value = [mock_activity]

        # Execute
        result = execution_engine.get_crypto_fees_by_orders(
            order_ids=["order-123"],
            symbol="BTC/USD",  # Our format
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 17),
        )

        # Verify
        assert result["total_fee_usd"] == 5.0, "total_fee_usd calculation mismatch"
        assert len(result["fee_details"]) == 1, "fee_details list length mismatch"
        assert result["fee_tier"] == "Tier 0: 0.25%", "fee_tier extraction mismatch"

        # Verify call
        mock_trading_client.get.assert_called()

    def test_get_crypto_fees_by_orders_multi_order_aggregation(
        self, execution_engine, mock_trading_client
    ):
        """Verify correct aggregation of CFEE for multiple orders within a trade."""
        # Setup multiple CFEE activities
        mock_activity1 = {
            "id": "cfee-entry",
            "symbol": "BTCUSD",
            "qty": "-0.0001",
            "price": "50000.0",
            "date": "2025-01-16",
            "description": "Tier 0: 0.25%",
        }
        mock_activity2 = {
            "id": "cfee-exit",
            "symbol": "BTCUSD",
            "qty": "-0.0001",
            "price": "55000.0",
            "date": "2025-01-17",
            "description": "Tier 0: 0.25%",
        }

        mock_trading_client.get.return_value = [mock_activity1, mock_activity2]

        # Execute
        result = execution_engine.get_crypto_fees_by_orders(
            order_ids=["order-entry", "order-exit"],
            symbol="BTC/USD",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 18),
        )

        # Verify aggregation: 5.0 + 5.5 = 10.5
        assert result["total_fee_usd"] == 10.5, "total_fee_usd aggregation mismatch"
        assert len(result["fee_details"]) == 2, "fee_details length mismatch"

    def test_get_crypto_fees_by_orders_api_failure(
        self, execution_engine, mock_trading_client
    ):
        """Ensure graceful handling when the Alpaca CFEE API call fails."""
        # Setup API failure
        mock_trading_client.get.side_effect = Exception("API rate limit exceeded")

        # Execute - should not raise
        result = execution_engine.get_crypto_fees_by_orders(
            order_ids=["order-123"],
            symbol="BTC/USD",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 17),
        )

        # Verify fallback to zero fees
        assert result["total_fee_usd"] == 0.0, "Expected 0.0 total fees on API failure"
        assert result["fee_details"] == [], "Expected empty fee_details on API failure"
        assert result["fee_tier"] is None, "Expected None fee_tier on API failure"

    def test_get_crypto_fees_by_orders_invalid_qty_price(
        self, execution_engine, mock_trading_client
    ):
        """Verify validation skips CFEE records with qty=0 or price=0."""
        # Setup invalid CFEE activity
        mock_activity = {
            "id": "cfee-invalid",
            "symbol": "BTCUSD",
            "qty": "0.0",  # Invalid!
            "price": "50000.0",
            "date": "2025-01-16",
        }

        mock_trading_client.get.return_value = [mock_activity]

        # Execute
        result = execution_engine.get_crypto_fees_by_orders(
            order_ids=["order-123"],
            symbol="BTC/USD",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 17),
        )

        # Verify invalid record was skipped
        assert (
            result["total_fee_usd"] == 0.0
        ), "Total fees should be 0.0 for invalid activity"
        assert (
            len(result["fee_details"]) == 0
        ), "Fee details should be empty for invalid activity"

    def test_get_crypto_fees_by_orders_retry_logic(
        self, execution_engine, mock_trading_client
    ):
        """Verify retry logic with exponential backoff on transient failures."""
        # Setup: Always fail to verify retry attempts
        mock_trading_client.get.side_effect = Exception("Persistent API error")

        # Mock sleep to avoid delays and track calls
        with patch("crypto_signals.engine.execution.sleep") as mock_sleep:
            # Execute
            result = execution_engine.get_crypto_fees_by_orders(
                order_ids=["order-123"],
                symbol="BTC/USD",
                start_date=date(2025, 1, 15),
                end_date=date(2025, 1, 17),
            )

        # Verify retries happened (3 attempts total)
        assert mock_trading_client.get.call_count == 3, "Expected 3 retry attempts"
        # Verify exponential backoff: sleep called 2 times
        assert mock_sleep.call_count == 2, "Expected 2 sleep calls for backoff"
        # Verify fallback to zero fees after all retries exhausted
        assert (
            result["total_fee_usd"] == 0.0
        ), "Expected 0.0 total fees after retries exhausted"
        assert (
            result["fee_details"] == []
        ), "Expected empty fee_details after retries exhausted"
        assert (
            result["fee_tier"] is None
        ), "Expected None fee_tier after retries exhausted"

    def test_get_current_fee_tier_success(self, execution_engine, mock_trading_client):
        """Verify successful retrieval of the current fee tier from Alpaca."""
        # Setup mock account
        mock_account = MagicMock()
        mock_account.crypto_tier = 0
        mock_trading_client.get_account.return_value = mock_account

        # Execute
        result = execution_engine.get_current_fee_tier()

        # Verify
        assert result["tier_name"] == "Tier 0", "Tier name mismatch"
        assert result["maker_fee_pct"] == 0.15, "Maker fee mismatch"
        assert result["taker_fee_pct"] == 0.25, "Taker fee mismatch"

    def test_get_current_fee_tier_api_failure(
        self, execution_engine, mock_trading_client
    ):
        """Ensure graceful handling when the Alpaca fee tier API call fails."""
        # Setup API failure
        mock_trading_client.get_account.side_effect = Exception("API error")

        # Execute - should not raise
        result = execution_engine.get_current_fee_tier()

        # Verify fallback to Tier 0
        assert result["tier_name"] == "Tier 0", "Expected Tier 0 fallback"
        assert result["maker_fee_pct"] == 0.15, "Expected Tier 0 maker fee fallback"
        assert result["taker_fee_pct"] == 0.25, "Expected Tier 0 taker fee fallback"


# =============================================================================
# MICRO-CAP EDGE CASE TESTS (Issue #136)
# =============================================================================
# Tests for negative stop-loss scenarios on low-priced assets (PEPE, SHIB)
# where ATR-based stop calculations can produce negative values.
# =============================================================================


class TestMicroCapEdgeCases:
    """Test suite for micro-cap token edge cases (Issue #136).

    Micro-cap tokens have extremely low prices (often < $0.0001), which can
    cause ATR-based stop-loss calculations to produce negative values:
        suggested_stop = low_price - (0.5 * atr)
        Example: 0.00000080 - (0.5 * 0.000002) = -0.00000020 ❌

    The fix uses floor-based calculation to prevent negatives:
        suggested_stop = max(SAFE_STOP_VAL, low_price - (0.5 * atr))
    """

    @pytest.fixture
    def pepe_usdt_signal_micro_cap(self):
        """PEPE/USD signal with extremely small prices (micro-cap edge case)."""
        return SignalFactory.build(
            signal_id="pepe-micro-cap-001",
            ds=date(2025, 1, 15),
            strategy_id="ELLIOTT_IMPULSE_WAVE",
            symbol="PEPE/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=0.00001200,  # ~$0.000012
            pattern_name="ELLIOTT_IMPULSE_WAVE",
            suggested_stop=0.00000080,  # Will be tested against floor
            status=SignalStatus.WAITING,
            take_profit_1=0.00001800,
            take_profit_2=0.00002400,
            side=OrderSide.BUY,
        )

    @pytest.fixture
    def shib_usdt_signal_micro_cap(self):
        """SHIB/USD signal with extreme volatility (high ATR)."""
        return SignalFactory.build(
            signal_id="shib-micro-cap-002",
            ds=date(2025, 1, 15),
            strategy_id="ELLIOTT_IMPULSE_WAVE",
            symbol="SHIB/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=0.00000950,  # ~$0.000010
            pattern_name="ELLIOTT_IMPULSE_WAVE",
            suggested_stop=0.00000001,  # SAFE_STOP_VAL (1e-8)
            status=SignalStatus.WAITING,
            take_profit_1=0.00001400,
            take_profit_2=0.00001900,
            side=OrderSide.BUY,
        )

    def test_calculate_qty_with_tiny_stop_loss(self, mock_settings, mock_trading_client):
        """Test quantity calculation when stop-loss is at safe floor (1e-8)."""
        # Arrange
        with patch(
            "crypto_signals.engine.execution.get_settings", return_value=mock_settings
        ):
            execution_engine = ExecutionEngine(
                trading_client=mock_trading_client,
                repository=MagicMock(),
            )

            signal = SignalFactory.build(
                signal_id="micro-qty-test",
                ds=date(2025, 1, 15),
                strategy_id="TEST",
                symbol="PEPE/USD",
                asset_class=AssetClass.CRYPTO,
                entry_price=0.00001200,
                pattern_name="TEST",
                suggested_stop=0.00000001,  # SAFE_STOP_VAL
                status=SignalStatus.WAITING,
                take_profit_1=0.00001800,
                side=OrderSide.BUY,
            )

            # Act
            qty = execution_engine._calculate_qty(signal)

            # Assert
            # Qty should be capped at MAX_POSITION_SIZE
            assert qty > 0, "Qty should be positive"
            assert qty == 1_000_000, f"Qty should be capped at MAX_POSITION_SIZE (1,000,000), but got {qty}"

    def test_calculate_qty_with_very_small_risk_per_share(
        self, mock_settings, mock_trading_client
    ):
        """Test qty calculation guards against extreme values (Issue #136)."""
        # Arrange
        with patch(
            "crypto_signals.engine.execution.get_settings", return_value=mock_settings
        ):
            execution_engine = ExecutionEngine(
                trading_client=mock_trading_client,
                repository=MagicMock(),
            )

            # Extreme case: entry and stop almost equal
            signal = SignalFactory.build(
                signal_id="extreme-qty-test",
                ds=date(2025, 1, 15),
                strategy_id="TEST",
                symbol="PEPE/USD",
                asset_class=AssetClass.CRYPTO,
                entry_price=0.00001200,
                pattern_name="TEST",
                suggested_stop=0.00001199,  # Extremely tight
                status=SignalStatus.WAITING,
                take_profit_1=0.00001800,
                side=OrderSide.BUY,
            )

            # Act
            qty = execution_engine._calculate_qty(signal)

            # Assert
            assert qty >= 0, "Qty should be non-negative"
            assert qty == 1_000_000, f"Qty should be capped at MAX_POSITION_SIZE (1,000,000), but got {qty}"

    def test_validate_signal_with_negative_stop_loss(self):
        """Test that _validate_signal_parameters catches negative stops.

        This tests the validation layer that should prevent negative stops
        from being used in bracket orders.
        """
        from crypto_signals.engine.signal_generator import SignalGenerator

        signal_gen = SignalGenerator(
            market_provider=MagicMock(),
            indicators=None,
        )

        # Params with negative stop (edge case before fix)
        params = {
            "signal_id": "neg-stop-test",
            "strategy_id": "ELLIOTT",
            "symbol": "PEPE/USD",
            "ds": date(2025, 1, 15),
            "asset_class": AssetClass.CRYPTO,
            "confluence_factors": [],
            "entry_price": 0.00001200,
            "pattern_name": "ELLIOTT_IMPULSE_WAVE",
            "suggested_stop": -0.00000020,  # NEGATIVE (pre-fix scenario)
            "invalidation_price": None,
            "take_profit_1": 0.00001800,
            "take_profit_2": None,
            "take_profit_3": None,
            "valid_until": None,
            "pattern_duration_days": None,
            "pattern_span_days": None,
            "pattern_classification": None,
            "structural_anchors": None,
            "harmonic_metadata": None,
            "created_at": None,
            "confluence_snapshot": None,
            "side": OrderSide.BUY,
        }

        rejection_reasons = signal_gen._validate_signal_parameters(params)

        # Should detect negative stop
        assert len(rejection_reasons) > 0, "Expected rejection reasons, got empty list"
        assert any(
            "Invalid Stop" in reason for reason in rejection_reasons
        ), f"Expected 'Invalid Stop' in rejection reasons: {rejection_reasons}"

    def test_validate_signal_with_safe_floor_stop_loss(self):
        """Test that safe floor stops (1e-8) pass validation.

        After the fix, suggested_stop should always be >= SAFE_STOP_VAL,
        so validation should pass.
        """
        from crypto_signals.engine.signal_generator import SignalGenerator

        signal_gen = SignalGenerator(
            market_provider=MagicMock(),
            indicators=None,
        )

        # Params with safe floor stop
        params = {
            "signal_id": "safe-stop-test",
            "strategy_id": "ELLIOTT",
            "symbol": "PEPE/USD",
            "ds": date(2025, 1, 15),
            "asset_class": AssetClass.CRYPTO,
            "confluence_factors": [],
            "entry_price": 0.00001200,
            "pattern_name": "ELLIOTT_IMPULSE_WAVE",
            "suggested_stop": 0.00000001,  # SAFE_STOP_VAL (1e-8)
            "invalidation_price": None,
            "take_profit_1": 0.00001800,
            "take_profit_2": 0.00002400,
            "take_profit_3": None,
            "valid_until": None,
            "pattern_duration_days": None,
            "pattern_span_days": None,
            "pattern_classification": None,
            "structural_anchors": None,
            "harmonic_metadata": None,
            "created_at": None,
            "confluence_snapshot": None,
            "side": OrderSide.BUY,
        }

        rejection_reasons = signal_gen._validate_signal_parameters(params)

        # Should NOT detect negative stop (stop is >= SAFE_STOP_VAL)
        assert not any(
            "Invalid Stop" in reason for reason in rejection_reasons
        ), f"Unexpected 'Invalid Stop' in rejection reasons: {rejection_reasons}"

    def test_pepe_signal_rr_ratio_with_micro_cap_prices(self):
        """Test R:R ratio calculation with micro-cap prices."""
        from crypto_signals.engine.signal_generator import SignalGenerator

        # Arrange
        signal_gen = SignalGenerator(
            market_provider=MagicMock(),
            indicators=None,
        )

        params = {
            "signal_id": "pepe-rr-test",
            "strategy_id": "ELLIOTT",
            "symbol": "PEPE/USD",
            "ds": date(2025, 1, 15),
            "asset_class": AssetClass.CRYPTO,
            "confluence_factors": [],
            "entry_price": 0.00001200,
            "pattern_name": "ELLIOTT_IMPULSE_WAVE",
            "suggested_stop": 0.00000001,  # SAFE_STOP_VAL
            "invalidation_price": None,
            "take_profit_1": 0.00001800,  # Profit > entry
            "take_profit_2": 0.00002400,
            "take_profit_3": None,
            "valid_until": None,
            "pattern_duration_days": None,
            "pattern_span_days": None,
            "pattern_classification": None,
            "structural_anchors": None,
            "harmonic_metadata": None,
            "created_at": None,
            "confluence_snapshot": {},
            "side": OrderSide.BUY,
        }

        # Act
        rejection_reasons = signal_gen._validate_signal_parameters(
            params, confluence_snapshot=params["confluence_snapshot"]
        )

        # Assert
        # R:R should be calculable (profit / risk)
        # profit = 0.00001800 - 0.00001200 = 0.00000600
        # risk = 0.00001200 - 0.00000001 = 0.00001199
        # R:R = 0.00000600 / 0.00001199 ≈ 0.5 (< 1.5, so should be rejected)
        assert any(
            "R:R" in reason for reason in rejection_reasons
        ), f"Expected 'R:R' in rejection reasons but got: {rejection_reasons}"


class TestCostBasisValidation:
    """Tests for notional value (cost basis) validation (Issue #192)."""

    def test_order_rejected_if_notional_value_too_low(
        self, execution_engine, sample_signal, mock_trading_client, mock_settings
    ):
        """Verify that a signal is rejected if qty * entry_price is below the minimum."""
        # Arrange
        # risk_per_share = 50.0. qty = 1.0 / 50.0 = 0.02. notional = 0.02 * 100 = $2 < $15.
        mock_settings.RISK_PER_TRADE = 1.0
        sample_signal.entry_price = 100.0
        sample_signal.suggested_stop = 50.0

        # Act
        position = execution_engine.execute_signal(sample_signal)

        # Assert
        assert position is None, "Position should be None when notional value is too low"
        mock_trading_client.submit_order.assert_not_called()

    def test_order_rejected_for_equity_below_minimum(
        self, execution_engine, mock_trading_client, mock_settings
    ):
        """Verify equity bracket orders are rejected when notional value is too low."""
        from crypto_signals.domain.schemas import AssetClass

        # Arrange
        mock_settings.RISK_PER_TRADE = 1.0
        equity_signal = SignalFactory.build(
            signal_id="equity-notional-test",
            ds=date(2025, 1, 15),
            strategy_id="TEST",
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            entry_price=150.0,
            pattern_name="TEST",
            suggested_stop=100.0,  # risk = 50
            status=SignalStatus.WAITING,
            take_profit_1=200.0,
            side=OrderSide.BUY,
        )

        # Act
        # qty = 1.0 / 50.0 = 0.02, notional = 0.02 * 150 = $3 < $15
        position = execution_engine.execute_signal(equity_signal)

        # Assert
        assert (
            position is None
        ), "Position should be None for equity below minimum notional"
        mock_trading_client.submit_order.assert_not_called()

    def test_is_notional_value_sufficient_returns_true_above_minimum(
        self, execution_engine, mock_settings
    ):
        """Verify helper method returns True for sufficient notional value."""
        # Arrange
        signal = SignalFactory.build(
            signal_id="notional-helper-test",
            ds=date(2025, 1, 15),
            strategy_id="TEST",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=100.0,
            pattern_name="TEST",
            suggested_stop=90.0,
            status=SignalStatus.WAITING,
            take_profit_1=120.0,
            side=OrderSide.BUY,
        )

        # Act
        # notional = 1.0 * 100 = $100 > $15
        result = execution_engine._is_notional_value_sufficient(1.0, signal)

        # Assert
        assert result is True, "Notional value check failed for sufficient value"

    def test_is_notional_value_sufficient_returns_false_below_minimum(
        self, execution_engine, mock_settings
    ):
        """Verify helper method returns False for insufficient notional value."""
        # Arrange
        signal = SignalFactory.build(
            signal_id="notional-helper-test-2",
            ds=date(2025, 1, 15),
            strategy_id="TEST",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=100.0,
            pattern_name="TEST",
            suggested_stop=90.0,
            status=SignalStatus.WAITING,
            take_profit_1=120.0,
            side=OrderSide.BUY,
        )

        # Act
        # notional = 0.1 * 100 = $10 < $15
        result = execution_engine._is_notional_value_sufficient(0.1, signal)

        # Assert
        assert result is False, "Notional value check passed for insufficient value"
