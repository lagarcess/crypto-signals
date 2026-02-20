"""Unit tests for the StateReconciler logic (migrated from ExecutionEngine)."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest
from alpaca.trading.models import Order
from crypto_signals.domain.schemas import (
    ExitReason,
    OrderSide,
    Position,
    TradeStatus,
)
from crypto_signals.engine.reconciler import StateReconciler
from crypto_signals.engine.reconciler_notifications import ReconcilerNotificationService


@pytest.fixture
def mock_alpaca():
    return MagicMock()


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def mock_discord():
    return MagicMock()


@pytest.fixture
def mock_notification_service(mock_discord):
    return ReconcilerNotificationService(mock_discord)


@pytest.fixture
def reconciler(mock_alpaca, mock_repo, mock_notification_service):
    return StateReconciler(
        alpaca_client=mock_alpaca,
        position_repo=mock_repo,
        notification_service=mock_notification_service,
    )


@pytest.fixture
def sample_position():
    """Create a sample OPEN position."""
    return Position(
        position_id="test-pos-sync-1",
        ds=date(2025, 1, 15),
        account_id="paper",
        symbol="BTC/USD",
        signal_id="test-signal-sync-1",
        alpaca_order_id="entry-order-1",
        tp_order_id="tp-order-1",
        sl_order_id="sl-order-1",
        status=TradeStatus.OPEN,
        entry_fill_price=50000.0,
        current_stop_loss=48000.0,
        qty=0.05,
        side=OrderSide.BUY,
    )


class TestHandleManualExitVerification:
    """Tests for the handle_manual_exit_verification method in StateReconciler."""

    def test_verify_manual_exit_success(
        self, reconciler, mock_alpaca, sample_position, mock_discord
    ):
        """Verify that a filled sell order marks the position as CLOSED/MANUAL_EXIT."""
        # 1. Mock get_orders to return a FILLED SELL order
        mock_sell_order = MagicMock(spec=Order)
        mock_sell_order.id = "manual-sell-order-123"
        mock_sell_order.status = "filled"
        mock_sell_order.side = "sell"
        mock_sell_order.filled_avg_price = "55000.0"
        mock_sell_order.filled_at = datetime(2025, 1, 16, 12, 0, 0, tzinfo=timezone.utc)

        mock_alpaca.get_orders.return_value = [mock_sell_order]

        # Execute
        result = reconciler.handle_manual_exit_verification(sample_position)

        # Verify
        assert isinstance(result, Position)
        assert sample_position.status == TradeStatus.CLOSED
        assert sample_position.exit_reason == ExitReason.MANUAL_EXIT
        assert sample_position.exit_fill_price == 55000.0
        assert sample_position.exit_order_id == "manual-sell-order-123"

        # Verify Discord notification sent
        mock_discord.send_message.assert_called_once()
        assert "MANUAL EXIT DETECTED" in mock_discord.send_message.call_args[0][0]

    def test_verify_manual_exit_failed_no_orders(
        self, reconciler, mock_alpaca, sample_position
    ):
        """Verify that if no orders are found, it returns False and keeps position OPEN."""
        # 1. Mock get_orders to return empty list
        mock_alpaca.get_orders.return_value = []

        # Execute
        result = reconciler.handle_manual_exit_verification(sample_position)

        # Verify
        assert result is None
        assert sample_position.status == TradeStatus.OPEN
        assert sample_position.exit_reason is None

    def test_verify_manual_exit_ignores_tp_sl_legs(
        self, reconciler, mock_alpaca, sample_position
    ):
        """Verify that known TP/SL legs are ignored in the manual exit search."""
        # 1. Return the TP order as the only "recent filled order"
        mock_tp_order = MagicMock(spec=Order)
        mock_tp_order.id = sample_position.tp_order_id  # Matches known TP
        mock_tp_order.status = "filled"

        mock_alpaca.get_orders.return_value = [mock_tp_order]

        # Execute
        result = reconciler.handle_manual_exit_verification(sample_position)

        # Verify
        assert result is None
        assert sample_position.status == TradeStatus.OPEN
