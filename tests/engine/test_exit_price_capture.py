"""
Unit tests for exit price capture functionality (Issue #141).

Tests cover:
- Emergency close with retry budget
- Scale-out with weighted average calculation
- Deferred backfill via sync_position_status
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from alpaca.trading.models import Order, OrderStatus
from crypto_signals.domain.schemas import (
    OrderSide,
    Position,
    TradeStatus,
    TradeType,
)
from crypto_signals.engine.execution import ExecutionEngine


class TestEmergencyCloseRetryBudget:
    """Test emergency close with retry budget for volatile markets."""

    def test_immediate_fill_capture(self, mock_trading_client):
        """Test emergency close with immediate fill price."""
        # Arrange
        engine = ExecutionEngine(trading_client=mock_trading_client)
        position = Position(
            position_id="test-pos-1",
            ds=datetime.now(timezone.utc).date(),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-1",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=49000.0,
            qty=0.1,
            side=OrderSide.BUY,
            trade_type=TradeType.EXECUTED.value,
        )

        # Mock order with immediate fill
        mock_order = MagicMock(spec=Order)
        mock_order.id = "order-123"
        mock_order.filled_avg_price = 51000.0
        mock_order.filled_at = datetime.now(timezone.utc)
        mock_order.status = OrderStatus.FILLED

        mock_trading_client.submit_order.return_value = mock_order

        # Act
        with (
            patch("crypto_signals.engine.execution.get_settings") as mock_settings,
            patch("crypto_signals.engine.execution.PositionRepository"),
        ):
            mock_settings.return_value.ENVIRONMENT = "PROD"
            result = engine.close_position_emergency(position)

        # Assert
        assert result is True
        assert position.exit_order_id == "order-123"
        assert position.exit_fill_price == 51000.0
        assert position.exit_time == mock_order.filled_at
        assert position.awaiting_backfill is False

    def test_retry_budget_success(self, mock_trading_client):
        """Test emergency close with retry budget (fills on retry 2)."""
        # Arrange
        engine = ExecutionEngine(trading_client=mock_trading_client)
        position = Position(
            position_id="test-pos-2",
            ds=datetime.now(timezone.utc).date(),
            account_id="paper",
            symbol="ETH/USD",
            signal_id="test-signal-2",
            status=TradeStatus.OPEN,
            entry_fill_price=3000.0,
            current_stop_loss=2900.0,
            qty=1.0,
            side=OrderSide.BUY,
            trade_type=TradeType.EXECUTED.value,
        )

        # Mock order with no immediate fill
        mock_order = MagicMock(spec=Order)
        mock_order.id = "order-456"
        mock_order.filled_avg_price = None  # Not filled immediately
        mock_order.filled_at = None
        mock_order.status = OrderStatus.ACCEPTED

        mock_trading_client.submit_order.return_value = mock_order

        # Mock get_order_details for retries
        # Retry 1: Still not filled
        mock_order_retry1 = MagicMock(spec=Order)
        mock_order_retry1.filled_avg_price = None
        mock_order_retry1.status = OrderStatus.ACCEPTED

        # Retry 2: Filled!
        mock_order_retry2 = MagicMock(spec=Order)
        mock_order_retry2.filled_avg_price = 3100.0
        mock_order_retry2.filled_at = datetime.now(timezone.utc)
        mock_order_retry2.status = OrderStatus.FILLED

        engine.get_order_details = MagicMock(
            side_effect=[mock_order_retry1, mock_order_retry2]
        )

        # Act
        with (
            patch("crypto_signals.engine.execution.get_settings") as mock_settings,
            patch("crypto_signals.engine.execution.PositionRepository"),
        ):
            mock_settings.return_value.ENVIRONMENT = "PROD"
            with patch("time.sleep"):  # Skip actual sleep
                result = engine.close_position_emergency(position)

        # Assert
        assert result is True
        assert position.exit_order_id == "order-456"
        assert position.exit_fill_price == 3100.0
        assert position.exit_time == mock_order_retry2.filled_at
        assert position.awaiting_backfill is False
        assert engine.get_order_details.call_count == 2  # Stopped after retry 2

    def test_retry_budget_exhausted(self, mock_trading_client):
        """Test emergency close with retry budget exhausted (awaiting backfill)."""
        # Arrange
        engine = ExecutionEngine(trading_client=mock_trading_client)
        position = Position(
            position_id="test-pos-3",
            ds=datetime.now(timezone.utc).date(),
            account_id="paper",
            symbol="SOL/USD",
            signal_id="test-signal-3",
            status=TradeStatus.OPEN,
            entry_fill_price=100.0,
            current_stop_loss=95.0,
            qty=10.0,
            side=OrderSide.BUY,
            trade_type=TradeType.EXECUTED.value,
        )

        # Mock order with no immediate fill
        mock_order = MagicMock(spec=Order)
        mock_order.id = "order-789"
        mock_order.filled_avg_price = None
        mock_order.filled_at = None
        mock_order.status = OrderStatus.ACCEPTED

        mock_trading_client.submit_order.return_value = mock_order

        # Mock get_order_details - never fills
        mock_order_retry = MagicMock(spec=Order)
        mock_order_retry.filled_avg_price = None
        mock_order_retry.status = OrderStatus.ACCEPTED

        engine.get_order_details = MagicMock(return_value=mock_order_retry)

        # Act
        with (
            patch("crypto_signals.engine.execution.get_settings") as mock_settings,
            patch("crypto_signals.engine.execution.PositionRepository"),
        ):
            mock_settings.return_value.ENVIRONMENT = "PROD"
            with patch("time.sleep"):  # Skip actual sleep
                result = engine.close_position_emergency(position)

        # Assert
        assert result is True  # Order submitted successfully
        assert position.exit_order_id == "order-789"
        assert position.exit_fill_price is None  # Not filled yet
        assert position.awaiting_backfill is True  # Marked for backfill
        assert engine.get_order_details.call_count == 3  # All 3 retries exhausted


class TestRetryFillPriceHelper:
    """Test the _retry_fill_price_capture helper method."""

    def test_retry_helper_immediate_success(self, mock_trading_client):
        """Test helper returns fill price on first retry."""
        # Arrange
        engine = ExecutionEngine(trading_client=mock_trading_client)

        mock_order = MagicMock(spec=Order)
        mock_order.filled_avg_price = 50000.0
        mock_order.filled_at = datetime.now(timezone.utc)

        engine.get_order_details = MagicMock(return_value=mock_order)

        # Act
        with patch("time.sleep"):
            result = engine._retry_fill_price_capture("order-123", "test-pos-1")

        # Assert
        assert result is not None
        fill_price, filled_at = result
        assert fill_price == 50000.0
        assert filled_at == mock_order.filled_at
        assert engine.get_order_details.call_count == 1

    def test_retry_helper_exhausted(self, mock_trading_client):
        """Test helper returns None when retries exhausted."""
        # Arrange
        engine = ExecutionEngine(trading_client=mock_trading_client)

        mock_order = MagicMock(spec=Order)
        mock_order.filled_avg_price = None

        engine.get_order_details = MagicMock(return_value=mock_order)

        # Act
        with patch("time.sleep"):
            result = engine._retry_fill_price_capture(
                "order-456", "test-pos-2", max_retries=2
            )

        # Assert
        assert result is None
        assert engine.get_order_details.call_count == 2


class TestScaleOutWeightedAverage:
    """Test scale-out with weighted average calculation."""

    def test_single_scale_out(self, mock_trading_client):
        """Test single scale-out (no weighted average needed)."""
        # Arrange
        engine = ExecutionEngine(trading_client=mock_trading_client)
        position = Position(
            position_id="test-pos-5",
            ds=datetime.now(timezone.utc).date(),
            account_id="paper",
            symbol="BTC/USD",
            signal_id="test-signal-5",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=49000.0,
            qty=1.0,
            side=OrderSide.BUY,
            trade_type=TradeType.EXECUTED.value,
        )

        # Mock order with immediate fill
        mock_order = MagicMock(spec=Order)
        mock_order.id = "scale-order-1"
        mock_order.filled_avg_price = 52000.0
        mock_order.status = OrderStatus.FILLED

        mock_trading_client.submit_order.return_value = mock_order

        # Act
        with (
            patch("crypto_signals.engine.execution.get_settings") as mock_settings,
            patch("crypto_signals.engine.execution.PositionRepository"),
        ):
            mock_settings.return_value.ENVIRONMENT = "PROD"
            result = engine.scale_out_position(position, scale_pct=0.5)

        # Assert
        assert result is True
        assert position.scaled_out_qty == 0.5
        assert position.scaled_out_price == 52000.0  # No averaging needed
        assert position.exit_fill_price == 52000.0  # Set for archival
        assert position.qty == 0.5  # Remaining
        assert len(position.scaled_out_prices) == 1
        assert position.scaled_out_prices[0]["price"] == 52000.0
        assert position.scaled_out_prices[0]["order_id"] == "scale-order-1"

    def test_multi_stage_weighted_average(self, mock_trading_client):
        """Test multi-stage scale-out with weighted average (TP1 + TP2)."""
        # Arrange
        engine = ExecutionEngine(trading_client=mock_trading_client)
        position = Position(
            position_id="test-pos-6",
            ds=datetime.now(timezone.utc).date(),
            account_id="paper",
            symbol="ETH/USD",
            signal_id="test-signal-6",
            status=TradeStatus.OPEN,
            entry_fill_price=3000.0,
            current_stop_loss=2900.0,
            qty=1.0,
            side=OrderSide.BUY,
            trade_type=TradeType.EXECUTED.value,
        )

        # Mock TP1 scale-out @ $3200
        mock_order_tp1 = MagicMock(spec=Order)
        mock_order_tp1.id = "tp1-order"
        mock_order_tp1.filled_avg_price = 3200.0
        mock_order_tp1.status = OrderStatus.FILLED

        mock_trading_client.submit_order.return_value = mock_order_tp1

        # Act: TP1 (50% @ $3200)
        with (
            patch("crypto_signals.engine.execution.get_settings") as mock_settings,
            patch("crypto_signals.engine.execution.PositionRepository"),
        ):
            mock_settings.return_value.ENVIRONMENT = "PROD"
            result_tp1 = engine.scale_out_position(position, scale_pct=0.5)

        # Assert TP1
        assert result_tp1 is True
        assert position.scaled_out_qty == 0.5
        assert position.scaled_out_price == 3200.0
        assert position.exit_fill_price == 3200.0
        assert position.qty == 0.5

        # Arrange TP2
        # Mock TP2 scale-out @ $3400
        mock_order_tp2 = MagicMock(spec=Order)
        mock_order_tp2.id = "tp2-order"
        mock_order_tp2.filled_avg_price = 3400.0
        mock_order_tp2.status = OrderStatus.FILLED

        mock_trading_client.submit_order.return_value = mock_order_tp2

        # Act: TP2 (50% of remaining = 0.25 total @ $3400)
        with (
            patch("crypto_signals.engine.execution.get_settings") as mock_settings,
            patch("crypto_signals.engine.execution.PositionRepository"),
        ):
            mock_settings.return_value.ENVIRONMENT = "PROD"
            result_tp2 = engine.scale_out_position(position, scale_pct=0.5)

        # Assert TP2 - Weighted Average
        assert result_tp2 is True
        assert position.scaled_out_qty == 0.75  # 0.5 + 0.25
        # Weighted avg: (0.5 * 3200 + 0.25 * 3400) / 0.75 = (1600 + 850) / 0.75 = 3266.67
        assert position.scaled_out_price == pytest.approx(3266.67, rel=0.01)
        assert position.exit_fill_price == pytest.approx(3266.67, rel=0.01)
        assert position.qty == 0.25  # Remaining
        assert len(position.scaled_out_prices) == 2

    def test_scale_out_retry_budget(self, mock_trading_client):
        """Test scale-out with retry budget."""
        # Arrange
        engine = ExecutionEngine(trading_client=mock_trading_client)
        position = Position(
            position_id="test-pos-7",
            ds=datetime.now(timezone.utc).date(),
            account_id="paper",
            symbol="SOL/USD",
            signal_id="test-signal-7",
            status=TradeStatus.OPEN,
            entry_fill_price=100.0,
            current_stop_loss=95.0,
            qty=10.0,
            side=OrderSide.BUY,
            trade_type=TradeType.EXECUTED.value,
        )

        # Mock order with no immediate fill
        mock_order = MagicMock(spec=Order)
        mock_order.id = "scale-retry-order"
        mock_order.filled_avg_price = None
        mock_order.status = OrderStatus.ACCEPTED

        mock_trading_client.submit_order.return_value = mock_order

        # Mock get_order_details - fills on retry 1
        mock_order_retry = MagicMock(spec=Order)
        mock_order_retry.filled_avg_price = 105.0
        mock_order_retry.status = OrderStatus.FILLED
        mock_order_retry.filled_at = datetime.now(timezone.utc)

        engine.get_order_details = MagicMock(return_value=mock_order_retry)

        # Act
        with (
            patch("crypto_signals.engine.execution.get_settings") as mock_settings,
            patch("crypto_signals.engine.execution.PositionRepository"),
        ):
            mock_settings.return_value.ENVIRONMENT = "PROD"
            with patch("time.sleep"):  # Skip actual sleep
                result = engine.scale_out_position(position, scale_pct=0.5)

        # Assert
        assert result is True
        assert position.scaled_out_price == 105.0
        assert position.exit_fill_price == 105.0
        assert position.awaiting_backfill is False
        assert engine.get_order_details.call_count == 1  # Stopped after retry 1


@pytest.fixture
def mock_trading_client():
    """Mock Alpaca TradingClient."""
    return MagicMock()
