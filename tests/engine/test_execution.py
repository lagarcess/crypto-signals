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
def execution_engine(mock_settings, mock_trading_client):
    """Create an ExecutionEngine with mocked dependencies."""
    with patch(
        "crypto_signals.engine.execution.get_settings", return_value=mock_settings
    ):
        engine = ExecutionEngine(trading_client=mock_trading_client)
        engine.settings = mock_settings
        return engine


class TestExecuteSignal:
    """Tests for the execute_signal method."""

    def test_bracket_order_construction(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify MarketOrderRequest is constructed with OrderClass.BRACKET."""
        # Setup
        mock_order = MagicMock()
        mock_order.id = "alpaca-order-123"
        mock_order.client_order_id = sample_signal.signal_id
        mock_order.status = "accepted"
        mock_trading_client.submit_order.return_value = mock_order

        # Execute
        position = execution_engine.execute_signal(sample_signal)

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
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify take_profit param matches signal's take_profit_1."""
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

        # Verify take profit
        assert order_request.take_profit.limit_price == round(
            sample_signal.take_profit_1, 2
        )

    def test_stop_loss_matches_signal(
        self, execution_engine, sample_signal, mock_trading_client
    ):
        """Verify stop_loss param matches signal's suggested_stop."""
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

        # Verify stop loss
        assert order_request.stop_loss.stop_price == round(
            sample_signal.suggested_stop, 2
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

        with patch(
            "crypto_signals.engine.execution.get_settings", return_value=mock_settings
        ):
            engine = ExecutionEngine(trading_client=mock_trading_client)
            engine.settings = mock_settings

            # Execute
            position = engine.execute_signal(sample_signal)

            # Verify no order was submitted
            mock_trading_client.submit_order.assert_not_called()
            assert position is None

    def test_execution_blocked_when_disabled(self, sample_signal, mock_trading_client):
        """Verify execution is blocked when ENABLE_EXECUTION=False."""
        # Setup settings with execution disabled
        mock_settings = MagicMock()
        mock_settings.is_paper_trading = True
        mock_settings.ENABLE_EXECUTION = False

        with patch(
            "crypto_signals.engine.execution.get_settings", return_value=mock_settings
        ):
            engine = ExecutionEngine(trading_client=mock_trading_client)
            engine.settings = mock_settings

            # Execute
            position = engine.execute_signal(sample_signal)

            # Verify no order was submitted
            mock_trading_client.submit_order.assert_not_called()
            assert position is None

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
