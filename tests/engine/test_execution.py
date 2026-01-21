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


@pytest.fixture
def mock_settings():
    """Fixture for mocking settings."""
    mock = MagicMock()
    mock.is_paper_trading = True
    mock.ENABLE_EXECUTION = True
    mock.RISK_PER_TRADE = 100.0
    mock.ENVIRONMENT = "PROD"
    mock.TTL_DAYS_POSITION = 90
    return mock


@pytest.fixture
def mock_trading_client():
    """Fixture for mocking TradingClient."""
    return MagicMock()


@pytest.fixture
def sample_signal():
    """Create a sample BUY signal for testing."""
    return Signal(
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
    return Signal(
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
    return Signal(
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
    with patch(
        "crypto_signals.engine.execution.get_settings", return_value=mock_settings
    ):
        engine = ExecutionEngine(trading_client=mock_trading_client)
        yield engine


class TestExecuteSignal:
    """Tests for the execute_signal method."""

    def test_bracket_order_construction(
        self, execution_engine, sample_equity_signal, mock_trading_client
    ):
        """Verify MarketOrderRequest is constructed with OrderClass.BRACKET for equity.

        Note: Bracket orders (OTOCO) are only supported for equities, not crypto.
        """
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_equity_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        position = execution_engine.execute_signal(sample_equity_signal)

        # Verify order was submitted and position returned
        assert position is not None
        mock_trading_client.submit_order.assert_called_once()

        # Get the order request that was passed
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]  # First positional argument

        # Verify bracket order class
        from alpaca.trading.enums import OrderClass

        assert order_request.order_class == OrderClass.BRACKET

    def test_take_profit_matches_signal(
        self, execution_engine, sample_equity_signal, mock_trading_client
    ):
        """Verify take_profit param matches signal's take_profit_1 for equity bracket orders."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_equity_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        execution_engine.execute_signal(sample_equity_signal)

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify take profit
        assert order_request.take_profit.limit_price == round(
            sample_equity_signal.take_profit_1, 2
        )

    def test_stop_loss_matches_signal(
        self, execution_engine, sample_equity_signal, mock_trading_client
    ):
        """Verify stop_loss param matches signal's suggested_stop for equity bracket orders."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_equity_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        execution_engine.execute_signal(sample_equity_signal)

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify stop loss
        assert order_request.stop_loss.stop_price == round(
            sample_equity_signal.suggested_stop, 2
        )

    def test_client_order_id_matches_signal_id(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify client_order_id equals signal.signal_id for traceability."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        execution_engine.execute_signal(sample_signal)

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify client_order_id
        assert order_request.client_order_id == sample_signal.signal_id

    def test_qty_calculation(self, execution_engine, sample_signal, mock_trading_client):
        """Verify qty calculation: RISK_PER_TRADE / (entry_price - stop_loss)."""
        # Setup - RISK_PER_TRADE = 100, entry = 50000, stop = 48000
        # Risk per share = 50000 - 48000 = 2000
        # Expected qty = 100 / 2000 = 0.05
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        execution_engine.execute_signal(sample_signal)

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify qty calculation: 100 / (50000 - 48000) = 0.05
        expected_qty = round(100.0 / 2000.0, 6)
        assert order_request.qty == expected_qty

    def test_execution_blocked_when_not_paper_trading(
        self, sample_signal, mock_trading_client
    ):
        """Verify execution is blocked when ALPACA_PAPER_TRADING=False."""
        # Setup settings with paper trading disabled
        mock_settings = MagicMock()
        mock_settings.is_paper_trading = False
        mock_settings.ENABLE_EXECUTION = True
        mock_settings.TTL_DAYS_POSITION = 90
        # Determine environment to test fallback
        mock_settings.ENVIRONMENT = "PROD"

        with patch(
            "crypto_signals.engine.execution.get_settings", return_value=mock_settings
        ):
            engine = ExecutionEngine(trading_client=mock_trading_client)

            # Execute
            position = engine.execute_signal(sample_signal)

            # Verify no LIVE order was submitted
            mock_trading_client.submit_order.assert_not_called()

            # Verify THEORETICAL position was created (fallback)
            assert position is not None
            assert position.trade_type == "THEORETICAL"

    def test_execution_blocked_when_disabled(self, sample_signal, mock_trading_client):
        """Verify execution is blocked when ENABLE_EXECUTION=False."""
        # Setup settings with execution disabled
        mock_settings = MagicMock()
        mock_settings.is_paper_trading = True
        mock_settings.ENABLE_EXECUTION = False
        mock_settings.ENVIRONMENT = "PROD"
        mock_settings.TTL_DAYS_POSITION = 90

        with patch(
            "crypto_signals.engine.execution.get_settings", return_value=mock_settings
        ):
            engine = ExecutionEngine(trading_client=mock_trading_client)

            # Execute
            position = engine.execute_signal(sample_signal)

            # Verify no LIVE order was submitted
            mock_trading_client.submit_order.assert_not_called()

            # Verify THEORETICAL position was created (fallback)
            assert position is not None
            assert position.trade_type == "THEORETICAL"

    def test_position_created_on_success(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify Position object is created with correct fields on success."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        position = execution_engine.execute_signal(sample_signal)

        # Verify position was created
        assert position is not None
        assert position.position_id == sample_signal.signal_id
        assert position.delete_at is not None
        assert position.signal_id == sample_signal.signal_id
        assert position.current_stop_loss == sample_signal.suggested_stop
        assert position.entry_fill_price == sample_signal.entry_price
        assert position.side == sample_signal.side

    def test_sell_order_side(
        self, execution_engine, sample_sell_signal, mock_trading_client
    ):
        """Verify SELL signals submit orders with OrderSide.SELL."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-sell-789"
        mock_order.client_order_id = sample_sell_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        position = execution_engine.execute_signal(sample_sell_signal)

        # Verify order was submitted
        assert position is not None
        mock_trading_client.submit_order.assert_called_once()

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify SELL order side
        from alpaca.trading.enums import OrderSide as AlpacaOrderSide

        assert order_request.side == AlpacaOrderSide.SELL
        assert position.side == OrderSide.SELL


class TestCryptoOrderFlow:
    """Tests for crypto-specific order flow (simple market orders, no bracket).

    Alpaca doesn't support OTOCO/bracket orders for crypto. Instead, we use
    simple market orders for entry and track SL/TP manually for exits.
    """

    def test_crypto_uses_simple_market_order(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify crypto orders do NOT include order_class (no bracket)."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        position = execution_engine.execute_signal(sample_signal)

        # Verify order was submitted
        assert position is not None
        mock_trading_client.submit_order.assert_called_once()

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify NO order_class parameter (simple market order)
        assert order_request.order_class is None

    def test_crypto_uses_gtc_time_in_force(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify crypto orders use GTC time_in_force (required by Alpaca)."""
        from alpaca.trading.enums import TimeInForce

        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-gtc"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        execution_engine.execute_signal(sample_signal)

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify GTC time_in_force
        assert order_request.time_in_force == TimeInForce.GTC

    def test_crypto_position_has_manual_sl_tp_fields(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify Position stores SL/TP for manual exit tracking."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-sltp"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        position = execution_engine.execute_signal(sample_signal)

        # Verify Position has SL/TP for manual tracking
        assert position is not None
        assert position.current_stop_loss == sample_signal.suggested_stop
        # TP order IDs should be None (no bracket legs)
        assert position.tp_order_id is None
        assert position.sl_order_id is None

    def test_crypto_no_take_profit_in_order(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify crypto orders do NOT include take_profit parameter."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-notp"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        execution_engine.execute_signal(sample_signal)

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify no take_profit in request (crypto uses manual tracking)
        assert (
            not hasattr(order_request, "take_profit") or order_request.take_profit is None
        )

    def test_crypto_no_stop_loss_in_order(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify crypto orders do NOT include stop_loss parameter."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-crypto-nosl"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        execution_engine.execute_signal(sample_signal)

        # Get the order request
        call_args = mock_trading_client.submit_order.call_args
        order_request = call_args[0][0]

        # Verify no stop_loss in request (crypto uses manual tracking)
        assert not hasattr(order_request, "stop_loss") or order_request.stop_loss is None


class TestValidateSignal:
    """Tests for signal validation."""

    def test_missing_take_profit_fails(self, execution_engine):
        """Verify validation fails when take_profit_1 is missing."""
        signal = Signal(
            signal_id="test-signal",
            ds=date(2025, 1, 15),
            strategy_id="TEST",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="TEST",
            suggested_stop=48000.0,
            take_profit_1=None,  # Missing!
        )

        assert execution_engine._validate_signal(signal) is False

    def test_missing_stop_fails(self, execution_engine):
        """Verify validation fails when suggested_stop is missing."""
        signal = Signal(
            signal_id="test-signal",
            ds=date(2025, 1, 15),
            strategy_id="TEST",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="TEST",
            suggested_stop=0,  # Invalid!
            take_profit_1=55000.0,
        )

        assert execution_engine._validate_signal(signal) is False

    def test_negative_stop_fails(self, execution_engine):
        """Verify validation fails when suggested_stop is negative."""
        signal = Signal(
            signal_id="test-signal",
            ds=date(2025, 1, 15),
            strategy_id="TEST",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=50000.0,
            pattern_name="TEST",
            suggested_stop=-100.0,  # Negative is invalid
            take_profit_1=55000.0,
        )

        assert execution_engine._validate_signal(signal) is False


class TestCalculateQty:
    """Tests for position size calculation."""

    def test_crypto_fractional_shares(self, execution_engine, sample_signal):
        """Verify crypto allows fractional shares with 6 decimals."""
        # sample_signal: entry=50000, stop=48000, risk_distance=2000
        qty = execution_engine._calculate_qty(sample_signal)

        # Crypto should be rounded to 6 decimals: 100 / 2000 = 0.05
        assert qty == round(100.0 / 2000.0, 6)

    def test_equity_fractional_shares(self, execution_engine):
        """Verify equity uses 4 decimal precision."""
        signal = Signal(
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

        qty = execution_engine._calculate_qty(signal)

        # Equity should be rounded to 4 decimals: 100 / (150 - 145) = 20
        assert qty == round(100.0 / 5.0, 4)


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
        assert position is None


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
        assert order is not None
        assert order.status == "filled"
        mock_trading_client.get_order_by_id.assert_called_once_with("order-123")

    def test_get_order_details_not_found(self, execution_engine, mock_trading_client):
        """Verify returns None when order not found."""
        # Setup
        mock_trading_client.get_order_by_id.side_effect = Exception("Order not found")

        # Execute
        order = execution_engine.get_order_details("nonexistent-order")

        # Verify
        assert order is None


class TestSyncPositionStatus:
    """Tests for the sync_position_status method."""

    def test_sync_extracts_leg_ids(self, execution_engine, mock_trading_client):
        """Verify TP and SL leg IDs are extracted from filled parent order."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup parent order with legs
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
        mock_order.filled_at = "2025-01-15T10:00:00Z"
        mock_order.filled_avg_price = "50100.0"
        mock_order.legs = [mock_tp_leg, mock_sl_leg]

        mock_trading_client.get_order_by_id.return_value = mock_order

        # Create position
        position = Position(
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

        # Execute
        updated = execution_engine.sync_position_status(position)

        # Verify leg IDs extracted
        assert updated.tp_order_id == "tp-leg-uuid-123"
        assert updated.sl_order_id == "sl-leg-uuid-456"
        assert updated.entry_fill_price == 50100.0

    def test_sync_detects_external_close_via_tp(
        self, execution_engine, mock_trading_client
    ):
        """Verify position marked CLOSED when TP order is filled."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup - parent and TP orders, TP is filled
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

        # Create position with TP order ID already set
        position = Position(
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

        # Execute
        updated = execution_engine.sync_position_status(position)

        # Verify
        assert updated.status == TradeStatus.CLOSED

    def test_sync_captures_exit_fill_price_on_tp_fill(
        self, execution_engine, mock_trading_client
    ):
        """Verify exit_fill_price is captured when TP order is filled."""
        from datetime import datetime, timezone

        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup - parent and TP orders, TP is filled with price
        mock_parent = MagicMock()
        mock_parent.status = "filled"
        mock_parent.filled_at = None
        mock_parent.filled_avg_price = None
        mock_parent.legs = []

        mock_tp_order = MagicMock()
        mock_tp_order.status = "filled"
        mock_tp_order.filled_avg_price = "55000.0"
        mock_tp_order.filled_at = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)

        def side_effect(order_id):
            if order_id == "parent-id":
                return mock_parent
            elif order_id == "tp-order-id":
                return mock_tp_order
            return None

        mock_trading_client.get_order_by_id.side_effect = side_effect

        position = Position(
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

        # Execute
        updated = execution_engine.sync_position_status(position)

        # Verify exit details captured
        assert updated.status == TradeStatus.CLOSED
        assert updated.exit_fill_price == 55000.0
        assert updated.exit_time == datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)

    def test_sync_captures_exit_details_on_sl_fill(
        self, execution_engine, mock_trading_client
    ):
        """Verify exit_fill_price is captured when SL order is filled."""
        from datetime import datetime, timezone

        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup - parent and SL orders, SL is filled with price
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
        mock_sl_order.filled_at = datetime(2025, 1, 15, 16, 0, 0, tzinfo=timezone.utc)

        def side_effect(order_id):
            if order_id == "parent-id":
                return mock_parent
            elif order_id == "tp-order-id":
                return mock_tp_order
            elif order_id == "sl-order-id":
                return mock_sl_order
            return None

        mock_trading_client.get_order_by_id.side_effect = side_effect

        position = Position(
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

        # Execute
        updated = execution_engine.sync_position_status(position)

        # Verify exit details captured
        assert updated.status == TradeStatus.CLOSED
        assert updated.exit_fill_price == 48000.0
        assert updated.exit_time == datetime(2025, 1, 15, 16, 0, 0, tzinfo=timezone.utc)

    def test_sync_detects_manual_exit_when_not_found(
        self, execution_engine, mock_trading_client
    ):
        """Verify position marked CLOSED (Manual Exit) when not found on Alpaca."""
        from datetime import datetime, timezone

        from crypto_signals.domain.schemas import ExitReason, Position, TradeStatus

        # Setup - parent order is filled (Entry)
        mock_parent = MagicMock()
        mock_parent.status = "filled"
        mock_parent.legs = []  # No active legs found (or irrelevant)

        # Setup - get_open_position raises 404 (Not Found)
        mock_trading_client.get_open_position.side_effect = Exception(
            "position not found (404)"
        )

        # Setup - get_orders finds a closing order
        mock_close_order = MagicMock()
        mock_close_order.id = "manual-close-id"
        mock_close_order.status = "filled"
        mock_close_order.filled_avg_price = "52000.0"
        mock_close_order.filled_at = datetime(2025, 1, 15, 17, 0, 0, tzinfo=timezone.utc)

        mock_trading_client.get_orders.return_value = [mock_close_order]

        # Setup get_order_by_id for parent
        mock_trading_client.get_order_by_id.return_value = mock_parent

        position = Position(
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

        # Execute
        updated = execution_engine.sync_position_status(position)

        # Verify
        assert updated.status == TradeStatus.CLOSED
        assert updated.exit_reason == ExitReason.MANUAL_EXIT
        assert updated.exit_fill_price == 52000.0
        assert updated.exit_time == datetime(2025, 1, 15, 17, 0, 0, tzinfo=timezone.utc)

        # Verify get_orders called with correct filter
        mock_trading_client.get_orders.assert_called_once()
        call_args = mock_trading_client.get_orders.call_args
        assert call_args[1]["filter"]["side"] == OrderSide.SELL  # Closing a BUY


class TestModifyStopLoss:
    """Tests for the modify_stop_loss method."""

    def test_modify_stop_loss_success(self, execution_engine, mock_trading_client):
        """Verify stop loss can be replaced when in replaceable state."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup - SL order in "new" state
        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"

        mock_replaced_order = MagicMock()
        mock_replaced_order.id = "new-sl-order-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced_order

        position = Position(
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

        # Execute
        result = execution_engine.modify_stop_loss(position, 49000.0)

        # Verify
        assert result is True
        assert position.sl_order_id == "new-sl-order-id"
        assert position.current_stop_loss == 49000.0
        mock_trading_client.replace_order_by_id.assert_called_once()

    def test_modify_stop_loss_pending_fails(self, execution_engine, mock_trading_client):
        """Verify replacement fails when order is in pending state."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup - SL order in "pending_replace" state
        mock_sl_order = MagicMock()
        mock_sl_order.status = "pending_replace"
        mock_trading_client.get_order_by_id.return_value = mock_sl_order

        position = Position(
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

        # Execute
        result = execution_engine.modify_stop_loss(position, 49000.0)

        # Verify
        assert result is False
        mock_trading_client.replace_order_by_id.assert_not_called()


class TestClosePositionEmergency:
    """Tests for the close_position_emergency method."""

    def test_emergency_close_cancels_all_legs(
        self, execution_engine, mock_trading_client
    ):
        """Verify all legs are canceled and market close order submitted."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup
        mock_close_order = MagicMock()
        mock_close_order.id = "close-order-id"
        mock_trading_client.submit_order.return_value = mock_close_order

        mock_parent_order = MagicMock()
        mock_parent_order.symbol = "BTC/USD"
        mock_trading_client.get_order_by_id.return_value = mock_parent_order

        position = Position(
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

        # Execute
        result = execution_engine.close_position_emergency(position)

        # Verify
        assert result is True
        assert position.status == TradeStatus.CLOSED

        # Verify cancel calls for TP and SL
        cancel_calls = mock_trading_client.cancel_order_by_id.call_args_list
        canceled_ids = [call[0][0] for call in cancel_calls]
        assert "tp-order-id" in canceled_ids
        assert "sl-order-id" in canceled_ids

        # Verify market close order submitted
        mock_trading_client.submit_order.assert_called_once()


class TestScaleOutPosition:
    """Tests for the scale_out_position method."""

    def test_scale_out_calculates_correct_qty(
        self, execution_engine, mock_trading_client
    ):
        """Verify 50% scale-out calculates the correct quantity."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup
        mock_close_order = MagicMock()
        mock_close_order.id = "scale-order-123"
        mock_close_order.filled_avg_price = "55000.0"
        mock_trading_client.submit_order.return_value = mock_close_order

        position = Position(
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

        # Execute
        result = execution_engine.scale_out_position(position, scale_pct=0.5)

        # Verify
        assert result is True
        call_args = mock_trading_client.submit_order.call_args[0][0]
        assert call_args.qty == 0.05  # 50% of 0.10

    def test_scale_out_updates_remaining_qty(self, execution_engine, mock_trading_client):
        """Verify position.qty is reduced after scale-out."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        mock_close_order = MagicMock()
        mock_close_order.id = "scale-order-123"
        mock_close_order.filled_avg_price = "55000.0"
        mock_trading_client.submit_order.return_value = mock_close_order

        position = Position(
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

        execution_engine.scale_out_position(position, scale_pct=0.5)

        # Verify remaining qty
        assert position.qty == 0.05

    def test_scale_out_captures_original_qty_once(
        self, execution_engine, mock_trading_client
    ):
        """Verify original_qty is set only on first scale-out, not overwritten."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        mock_close_order = MagicMock()
        mock_close_order.id = "scale-order-123"
        mock_close_order.filled_avg_price = "55000.0"
        mock_trading_client.submit_order.return_value = mock_close_order

        position = Position(
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

        # First scale-out (50%): 1.0 -> 0.5
        execution_engine.scale_out_position(position, scale_pct=0.5)
        assert position.original_qty == 1.0  # Captured before first scale

        # Second scale-out (50% of remaining): 0.5 -> 0.25
        execution_engine.scale_out_position(position, scale_pct=0.5)
        assert position.original_qty == 1.0  # Still the original, NOT overwritten

    def test_scale_out_appends_to_prices_list(
        self, execution_engine, mock_trading_client
    ):
        """Verify scaled_out_prices list accumulates for multi-stage exits."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # First scale-out at $55,000
        mock_order_1 = MagicMock()
        mock_order_1.id = "scale-order-1"
        mock_order_1.filled_avg_price = "55000.0"

        # Second scale-out at $58,000
        mock_order_2 = MagicMock()
        mock_order_2.id = "scale-order-2"
        mock_order_2.filled_avg_price = "58000.0"

        mock_trading_client.submit_order.side_effect = [mock_order_1, mock_order_2]

        position = Position(
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

        # First scale-out
        execution_engine.scale_out_position(position, scale_pct=0.5)
        # Second scale-out
        execution_engine.scale_out_position(position, scale_pct=0.5)

        # Verify prices list accumulated
        assert len(position.scaled_out_prices) == 2
        assert position.scaled_out_prices[0]["price"] == 55000.0
        assert position.scaled_out_prices[0]["qty"] == 0.5
        assert position.scaled_out_prices[1]["price"] == 58000.0
        assert position.scaled_out_prices[1]["qty"] == 0.25  # 50% of remaining 0.5

    def test_scale_out_fails_with_no_qty(self, execution_engine, mock_trading_client):
        """Verify returns False when position has no quantity."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        position = Position(
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

        result = execution_engine.scale_out_position(position, scale_pct=0.5)

        assert result is False
        mock_trading_client.submit_order.assert_not_called()

    def test_scale_out_handles_order_failure(self, execution_engine, mock_trading_client):
        """Verify failed_reason is set when order submission fails."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        mock_trading_client.submit_order.side_effect = Exception("Insufficient funds")

        position = Position(
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

        result = execution_engine.scale_out_position(position, scale_pct=0.5)

        assert result is False
        assert "Scale-out failed" in position.failed_reason


class TestMoveStopToBreakeven:
    """Tests for the move_stop_to_breakeven method."""

    def test_breakeven_moves_stop_to_entry(self, execution_engine, mock_trading_client):
        """Verify stop is moved to entry price (with buffer)."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # Setup - SL order in replaceable state
        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"

        mock_replaced_order = MagicMock()
        mock_replaced_order.id = "new-sl-order-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced_order

        position = Position(
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

        result = execution_engine.move_stop_to_breakeven(position)

        assert result is True
        # Entry + 0.1% buffer = 50000 * 1.001 = 50050
        assert position.current_stop_loss == 50050.0

    def test_breakeven_applies_buffer_for_longs(
        self, execution_engine, mock_trading_client
    ):
        """Verify 0.1% buffer is above entry for long positions."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"
        mock_replaced = MagicMock()
        mock_replaced.id = "new-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced

        position = Position(
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

        execution_engine.move_stop_to_breakeven(position)

        # Long: 100 * 1.001 = 100.10, rounded to 100.1
        assert position.current_stop_loss == 100.1

    def test_breakeven_applies_buffer_for_shorts(
        self, execution_engine, mock_trading_client
    ):
        """Verify 0.1% buffer is below entry for short positions."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"
        mock_replaced = MagicMock()
        mock_replaced.id = "new-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced

        position = Position(
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

        execution_engine.move_stop_to_breakeven(position)

        # Short: 100 * 0.999 = 99.90, rounded to 99.9
        assert position.current_stop_loss == 99.9

    def test_breakeven_sets_flag(self, execution_engine, mock_trading_client):
        """Verify breakeven_applied flag is set to True on success."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        mock_sl_order = MagicMock()
        mock_sl_order.status = "new"
        mock_replaced = MagicMock()
        mock_replaced.id = "new-id"

        mock_trading_client.get_order_by_id.return_value = mock_sl_order
        mock_trading_client.replace_order_by_id.return_value = mock_replaced

        position = Position(
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

        assert position.breakeven_applied is False
        execution_engine.move_stop_to_breakeven(position)
        assert position.breakeven_applied is True

    def test_breakeven_fails_without_entry_price(
        self, execution_engine, mock_trading_client
    ):
        """Verify returns False when entry_fill_price is missing."""
        from crypto_signals.domain.schemas import Position, TradeStatus

        # Create valid position first, then set entry_fill_price to None
        position = Position(
            position_id="test-be-no-entry",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-be",
            alpaca_order_id="parent-id",
            sl_order_id="sl-id",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,  # Required for model validation
            current_stop_loss=48000.0,
            qty=0.05,
            side=OrderSide.BUY,
        )
        # Simulate edge case where entry_fill_price might be cleared
        position.entry_fill_price = None

        result = execution_engine.move_stop_to_breakeven(position)

        assert result is False
        mock_trading_client.replace_order_by_id.assert_not_called()
