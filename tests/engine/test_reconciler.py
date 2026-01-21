"""Unit tests for the StateReconciler module."""

from datetime import date
from unittest.mock import MagicMock

import pytest
from crypto_signals.domain.schemas import (
    ExitReason,
    OrderSide,
    Position,
    TradeStatus,
)
from crypto_signals.engine.reconciler import StateReconciler
from crypto_signals.repository.firestore import PositionRepository


@pytest.fixture
def mock_trading_client():
    """Fixture for mocking TradingClient."""
    return MagicMock()


@pytest.fixture
def mock_position_repo():
    """Fixture for mocking PositionRepository."""
    return MagicMock(spec=PositionRepository)


@pytest.fixture
def mock_discord_client():
    """Fixture for mocking DiscordClient."""
    return MagicMock()


@pytest.fixture
def mock_settings():
    """Fixture for mocking settings."""
    mock = MagicMock()
    mock.ENVIRONMENT = "PROD"
    mock.TTL_DAYS_POSITION = 90
    return mock


@pytest.fixture
def sample_open_position():
    """Create a sample OPEN position."""
    return Position(
        position_id="signal-123",
        ds=date(2025, 1, 15),
        account_id="paper",
        symbol="BTC/USD",
        signal_id="signal-123",
        alpaca_order_id="order-123",
        status=TradeStatus.OPEN,
        entry_fill_price=50000.0,
        current_stop_loss=48000.0,
        qty=0.01,
        side=OrderSide.BUY,
        target_entry_price=50000.0,
    )


@pytest.fixture
def sample_alpaca_position():
    """Create a sample Alpaca position object."""
    mock_pos = MagicMock()
    mock_pos.symbol = "BTC/USD"
    mock_pos.qty = 0.01
    mock_pos.side = "long"
    return mock_pos


# ============================================================================
# Test Classes organized by functionality
# ============================================================================


class TestStateReconcilerInitialization:
    """Test StateReconciler initialization and dependency injection."""

    def test_init_stores_dependencies(
        self, mock_trading_client, mock_position_repo, mock_discord_client, mock_settings
    ):
        """StateReconciler stores injected dependencies."""
        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        assert reconciler.alpaca == mock_trading_client
        assert reconciler.position_repo == mock_position_repo
        assert reconciler.discord == mock_discord_client
        assert reconciler.settings == mock_settings


class TestDetectZombies:
    """Test zombie detection: Firestore OPEN, Alpaca closed."""

    def test_detect_zombies(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_open_position,
        sample_alpaca_position,
    ):
        """Zombies are detected: Firestore OPEN, Alpaca closed."""
        # Alpaca has NO position
        mock_trading_client.get_all_positions.return_value = []

        # Firestore has OPEN position
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        # Zombie detected
        assert "BTC/USD" in report.zombies
        assert len(report.zombies) == 1

    def test_reconcile_handles_multiple_zombies(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """Reconciliation handles multiple zombies."""
        # Create two open positions in Firestore
        pos1 = MagicMock(spec=Position)
        pos1.symbol = "BTC/USD"
        pos1.status = TradeStatus.OPEN
        pos1.position_id = "signal-1"
        pos1.trade_type = "EXECUTED"

        pos2 = MagicMock(spec=Position)
        pos2.symbol = "ETH/USD"
        pos2.status = TradeStatus.OPEN
        pos2.position_id = "signal-2"
        pos2.trade_type = "EXECUTED"

        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = [pos1, pos2]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        assert len(report.zombies) == 2
        assert "BTC/USD" in report.zombies
        assert "ETH/USD" in report.zombies


class TestDetectOrphans:
    """Test orphan detection: Alpaca OPEN, Firestore missing."""

    def test_detect_orphans(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_alpaca_position,
    ):
        """Orphans are detected: Alpaca OPEN, Firestore missing."""
        # Alpaca has open position
        mock_trading_client.get_all_positions.return_value = [sample_alpaca_position]

        # Firestore has NO position
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        # Orphan detected
        assert "BTC/USD" in report.orphans
        assert len(report.orphans) == 1

    def test_reconcile_handles_multiple_orphans(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """Reconciliation handles multiple orphans."""
        pos1 = MagicMock()
        pos1.symbol = "BTC/USD"

        pos2 = MagicMock()
        pos2.symbol = "ETH/USD"

        mock_trading_client.get_all_positions.return_value = [pos1, pos2]
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        assert len(report.orphans) == 2
        assert "BTC/USD" in report.orphans
        assert "ETH/USD" in report.orphans

    def test_reconcile_reports_critical_issues(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_alpaca_position,
    ):
        """Orphan positions are reported as critical issues."""
        mock_trading_client.get_all_positions.return_value = [sample_alpaca_position]
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        assert len(report.critical_issues) > 0
        assert any("BTC/USD" in issue for issue in report.critical_issues)


class TestHealingAndAlerts:
    """Test zombie healing and orphan alerts."""

    def test_heal_zombie_marks_closed_externally(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_open_position,
    ):
        """Healing zombie marks position CLOSED_EXTERNALLY."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        reconciler.reconcile()

        # Verify update was called
        mock_position_repo.update_position.assert_called()

        # Verify the position was marked CLOSED_EXTERNALLY
        called_position = mock_position_repo.update_position.call_args[0][0]
        assert called_position.status == TradeStatus.CLOSED
        assert called_position.exit_reason == ExitReason.CLOSED_EXTERNALLY

    def test_alert_orphan_sends_discord_message(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_alpaca_position,
    ):
        """Orphan detection sends Discord message."""
        mock_trading_client.get_all_positions.return_value = [sample_alpaca_position]
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        reconciler.reconcile()

        # Verify Discord was called for orphan alert
        assert mock_discord_client.send_message.called


class TestReconciliationBehavior:
    """Test reconciliation behavior, reports, and idempotency."""

    def test_reconcile_returns_report(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """reconcile() returns a ReconciliationReport."""
        # Mock empty positions (no zombies, no orphans)
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        assert report is not None
        assert hasattr(report, "zombies")
        assert hasattr(report, "orphans")
        assert hasattr(report, "reconciled_count")
        assert hasattr(report, "timestamp")
        assert hasattr(report, "duration_seconds")

    def test_reconcile_idempotent(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_open_position,
    ):
        """Running reconciliation twice produces consistent results."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report1 = reconciler.reconcile()
        report2 = reconciler.reconcile()

        assert len(report1.zombies) == len(report2.zombies)
        assert len(report1.orphans) == len(report2.orphans)

    def test_reconcile_reports_duration(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """Reconciliation report includes execution duration."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        assert report.duration_seconds >= 0.0
        assert isinstance(report.duration_seconds, float)


class TestEnvironmentGating:
    """Test environment isolation and gating."""

    def test_reconcile_non_prod_environment(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """Reconciliation respects ENVIRONMENT != PROD."""
        mock_settings.ENVIRONMENT = "DEV"
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        reconciler.reconcile()

        # Execution should be skipped
        mock_trading_client.get_all_positions.assert_not_called()


class TestErrorHandling:
    """Test error handling and resilience."""

    def test_reconcile_error_handling_get_all_positions_fails(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """Reconciliation handles Alpaca API errors gracefully."""
        mock_trading_client.get_all_positions.side_effect = Exception("API Error")
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        # Should not raise, should return error report
        report = reconciler.reconcile()

        assert len(report.critical_issues) > 0

    def test_reconcile_error_handling_firestore_fails(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """Reconciliation handles Firestore errors gracefully."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.side_effect = Exception("DB Error")

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        # Should not raise, should return error report
        report = reconciler.reconcile()

        assert len(report.critical_issues) > 0
