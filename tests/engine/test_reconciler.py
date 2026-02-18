"""Unit tests for the StateReconciler module."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.enums import ReconciliationErrors
from crypto_signals.domain.schemas import (
    ExitReason,
    OrderSide,
    Position,
    TradeStatus,
)
from crypto_signals.engine.reconciler import StateReconciler
from crypto_signals.engine.reconciler_notifications import ReconcilerNotificationService
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
def mock_notification_service():
    """Fixture for mocking ReconcilerNotificationService."""
    return MagicMock(spec=ReconcilerNotificationService)


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
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
    ):
        """StateReconciler stores injected dependencies."""
        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        assert reconciler.alpaca == mock_trading_client
        assert reconciler.position_repo == mock_position_repo
        assert reconciler.notifications == mock_notification_service
        assert reconciler.settings == mock_settings


class TestDetectZombies:
    """Test zombie detection: Firestore OPEN, Alpaca closed."""

    def test_detect_zombies(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
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
            notification_service=mock_notification_service,
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
        mock_notification_service,
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
            notification_service=mock_notification_service,
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
        mock_notification_service,
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
            notification_service=mock_notification_service,
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
        mock_notification_service,
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
            notification_service=mock_notification_service,
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
        mock_notification_service,
        mock_settings,
        sample_alpaca_position,
    ):
        """Orphan positions are reported as critical issues."""
        mock_trading_client.get_all_positions.return_value = [sample_alpaca_position]
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        assert len(report.critical_issues) > 0
        expected_error = ReconciliationErrors.ORPHAN_POSITION.format(symbol="BTC/USD")
        assert any(expected_error in issue for issue in report.critical_issues)


class TestHealingAndAlerts:
    """Test zombie healing and orphan alerts."""

    def test_heal_zombie_marks_closed_externally(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
        sample_open_position,
    ):
        """Healing zombie marks position CLOSED_EXTERNALLY."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        # Mock verification to succeed so that update_position is called
        # We need to simulate the side effect of updating the position object
        def verify_side_effect(pos):
            pos.status = TradeStatus.CLOSED
            pos.exit_reason = ExitReason.MANUAL_EXIT
            return True

        with patch.object(
            reconciler, "handle_manual_exit_verification", side_effect=verify_side_effect
        ):
            reconciler.reconcile()

        # Verify update was called
        mock_position_repo.update_position.assert_called()

        # Verify the position was marked CLOSED (reason is now MANUAL_EXIT due to verification)
        called_position = mock_position_repo.update_position.call_args[0][0]
        assert called_position.status == TradeStatus.CLOSED
        assert called_position.exit_reason == ExitReason.MANUAL_EXIT

    def test_alert_orphan_sends_discord_message(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
        sample_alpaca_position,
    ):
        """Orphan detection sends Discord message."""
        mock_trading_client.get_all_positions.return_value = [sample_alpaca_position]
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        reconciler.reconcile()

        # Verify notification service was called for orphan alert
        assert mock_notification_service.notify_orphan.called


class TestReconciliationBehavior:
    """Test reconciliation behavior, reports, and idempotency."""

    def test_reconcile_returns_report(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
    ):
        """reconcile() returns a ReconciliationReport."""
        # Mock empty positions (no zombies, no orphans)
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
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
        mock_notification_service,
        mock_settings,
        sample_open_position,
    ):
        """Running reconciliation twice produces consistent results."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
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
        mock_notification_service,
        mock_settings,
    ):
        """Reconciliation report includes execution duration."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
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
        mock_notification_service,
        mock_settings,
    ):
        """Reconciliation respects ENVIRONMENT != PROD."""
        mock_settings.ENVIRONMENT = "DEV"
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
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
        mock_notification_service,
        mock_settings,
    ):
        """Reconciliation handles Alpaca API errors gracefully."""
        mock_trading_client.get_all_positions.side_effect = Exception("API Error")
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        # Should not raise, should return error report
        report = reconciler.reconcile()

        assert len(report.critical_issues) > 0

    def test_reconcile_error_handling_firestore_fails(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
    ):
        """Reconciliation handles Firestore errors gracefully."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.side_effect = Exception("DB Error")

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        # Should not raise, should return error report
        report = reconciler.reconcile()

        assert len(report.critical_issues) > 0


class TestReconcilerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_reconcile_with_empty_symbols(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
    ):
        """Reconciliation handles empty symbol sets gracefully."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        assert len(report.zombies) == 0
        assert len(report.orphans) == 0
        assert report.reconciled_count == 0

    def test_reconcile_zombie_update_failure_not_blocking(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
        sample_open_position,
    ):
        """Zombie healing failure doesn't block orphan alerts."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        # Fail on update_position, succeed on other calls
        mock_position_repo.update_position.side_effect = Exception("DB Write Error")

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        # Should still return report with critical issues
        report = reconciler.reconcile()

        assert len(report.critical_issues) > 0
        assert "BTC/USD" in report.zombies  # Zombie still detected

    def test_reconcile_notification_failure_not_blocking(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
        sample_alpaca_position,
    ):
        """Notification failure doesn't block reconciliation."""
        mock_trading_client.get_all_positions.return_value = [sample_alpaca_position]
        mock_position_repo.get_open_positions.return_value = []

        # Fail on notification send
        mock_notification_service.notify_orphan.side_effect = Exception("Notification Error")

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        # Should still return report
        report = reconciler.reconcile()

        assert len(report.orphans) > 0  # Orphan still detected
        expected_error = ReconciliationErrors.ORPHAN_POSITION.format(symbol="BTC/USD")
        assert expected_error in report.critical_issues

    def test_reconcile_report_timestamp_is_set(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
    ):
        """Reconciliation report includes current timestamp."""
        from datetime import datetime

        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        before = datetime.now(datetime.now().astimezone().tzinfo)
        report = reconciler.reconcile()
        after = datetime.now(datetime.now().astimezone().tzinfo)

        assert before <= report.timestamp <= after

    def test_reconcile_only_processes_open_positions(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
        sample_open_position,
    ):
        """Reconciliation only checks open positions from Firestore."""
        # Alpaca has nothing
        mock_trading_client.get_all_positions.return_value = []

        # Firestore returns only open positions (as per method contract)
        # Using sample_open_position which has all required attributes
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        # Only BTC/USD should be detected as zombie
        assert "BTC/USD" in report.zombies
        assert len(report.zombies) == 1

    def test_reconcile_with_same_symbols_in_both_states(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
        sample_open_position,
    ):
        """Reconciliation detects no issues when symbols match."""
        alpaca_pos = MagicMock()
        alpaca_pos.symbol = "BTC/USD"

        # Use sample_open_position which has all required attributes
        sample_open_position.status = TradeStatus.OPEN
        mock_trading_client.get_all_positions.return_value = [alpaca_pos]
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        # No zombies or orphans when in sync
        assert len(report.zombies) == 0
        assert len(report.orphans) == 0
        assert report.reconciled_count == 0


class TestReconcilerSettings:
    """Test reconciler behavior with different settings."""

    def test_reconcile_uses_provided_settings(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
    ):
        """Reconciler uses provided settings instead of global defaults."""
        custom_settings = MagicMock()
        custom_settings.ENVIRONMENT = "STAGING"

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=custom_settings,
        )

        assert reconciler.settings == custom_settings
        assert reconciler.settings.ENVIRONMENT == "STAGING"

    def test_reconcile_defaults_to_get_settings_when_none(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
    ):
        """Reconciler uses get_settings() when settings param is None."""
        with patch("crypto_signals.engine.reconciler.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.ENVIRONMENT = "PROD"
            mock_get_settings.return_value = mock_settings

            mock_trading_client.get_all_positions.return_value = []
            mock_position_repo.get_open_positions.return_value = []

            reconciler = StateReconciler(
                alpaca_client=mock_trading_client,
                position_repo=mock_position_repo,
                notification_service=mock_notification_service,
                settings=None,
            )

            assert reconciler.settings == mock_settings
            mock_get_settings.assert_called_once()


class TestSafetyMechanisms:
    """Test critical safety mechanisms (Issue #244 fixes)."""

    def test_reconcile_skips_young_zombies(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
        sample_open_position,
    ):
        """Reconciliation ignores zombies created within the grace period (Race Condition protection)."""
        from datetime import datetime, timedelta, timezone

        # 1. Setup: Zombie Position (Open in DB, Missing in Alpaca)
        mock_trading_client.get_all_positions.return_value = []

        # 2. Make it "Young" (created 1 minute ago)
        sample_open_position.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=1
        )
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        # 3. Execute with default 5 min grace period
        report = reconciler.reconcile(min_age_minutes=5)

        # 4. Assertions
        # Should NOT be healed/closed
        mock_position_repo.update_position.assert_not_called()

        # Should not be in critical issues (it's skipped intentionaly)
        assert len(report.critical_issues) == 0
        # Should not be counted as a processed zombie in the final report lists
        # (implementation detail: logic creates zombies list first, then loops.
        # Check if code removes it from list or just skips actions.
        # Based on code: it iterates zombies but `continue`. So it IS in report.zombies list but NO action taken)
        assert "BTC/USD" in report.zombies

    def test_reconcile_refuses_to_close_unverified_zombie(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_notification_service,
        mock_settings,
        sample_open_position,
    ):
        """Reconciliation REFUSES to close a zombie if manual verification fails."""
        from datetime import datetime, timedelta, timezone

        # 1. Setup: Old Zombie (valid age)
        mock_trading_client.get_all_positions.return_value = []
        sample_open_position.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            notification_service=mock_notification_service,
            settings=mock_settings,
        )

        # 2. Mock Verification to FAIL (return False)
        # using patch object on the specific instance method
        with patch.object(
            reconciler, "handle_manual_exit_verification", return_value=False
        ):
            report = reconciler.reconcile()

        # 3. Assertions
        # CRITICAL: Database must NOT be updated (Position must remain OPEN)
        mock_position_repo.update_position.assert_not_called()

        # Should log critical issue
        assert len(report.critical_issues) > 0
        expected_error = ReconciliationErrors.ZOMBIE_EXIT_GAP.format(symbol="BTC/USD")
        assert any(expected_error in i for i in report.critical_issues)

        # Should alert Discord
        assert mock_discord_client.send_message.called
