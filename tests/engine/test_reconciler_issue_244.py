import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from crypto_signals.domain.schemas import (
    Position,
    TradeStatus,
)
from crypto_signals.engine.reconciler import StateReconciler
from crypto_signals.engine.reconciler_notifications import ReconcilerNotificationService


class TestReconcilerReproduction(unittest.TestCase):
    def setUp(self):
        self.mock_alpaca = MagicMock()
        self.mock_repo = MagicMock()
        self.mock_discord = MagicMock()
        self.mock_notifications = ReconcilerNotificationService(self.mock_discord)
        self.mock_settings = MagicMock()
        self.mock_settings.ENVIRONMENT = "PROD"

        self.reconciler = StateReconciler(
            alpaca_client=self.mock_alpaca,
            position_repo=self.mock_repo,
            notification_service=self.mock_notifications,
            settings=self.mock_settings,
        )

    def test_race_condition_zombie_kill(self):
        """
        Verify Fix for Issue #244: Race Condition.
        A position created < 5 mins ago is ignored (skipped) to prevent race conditions.
        """
        # 1. Setup: Alpaca returns empty
        self.mock_alpaca.get_all_positions.return_value = []

        # 2. Setup: Firestore has a VERY NEW position
        now = datetime.now(timezone.utc)
        pos = MagicMock(spec=Position)
        pos.symbol = "BTC/USD"
        pos.status = TradeStatus.OPEN
        pos.position_id = "pos-123"
        pos.trade_type = "EXECUTED"
        pos.created_at = now - timedelta(seconds=10)  # 10 seconds old

        self.mock_repo.get_open_positions.return_value = [pos]

        # 3. Execution
        self.reconciler.reconcile(min_age_minutes=5)

        # 4. Assertion: It should NOT be closed.
        self.mock_repo.update_position.assert_not_called()
        print(
            "\n[Verification] Race condition fix confirmed: Young position was SKIPPED."
        )

    def test_manual_verification_usage_failure(self):
        """
        Verify Fix for Issue #244: Unused Verification Logic.
        If verification fails (returns False), position is NOT closed.
        """
        # 1. Setup: Alpaca empty
        self.mock_alpaca.get_all_positions.return_value = []

        # 2. Setup: Old position (valid zombie candidate)
        now = datetime.now(timezone.utc)
        pos = MagicMock(spec=Position)
        pos.symbol = "ETH/USD"
        pos.status = TradeStatus.OPEN
        pos.position_id = "pos-456"
        pos.trade_type = "EXECUTED"
        pos.created_at = now - timedelta(minutes=10)  # 10 minutes old (older than 5)

        self.mock_repo.get_open_positions.return_value = [pos]

        # 3. Mock handle_manual_exit_verification to return False
        with patch.object(
            self.reconciler, "handle_manual_exit_verification", return_value=False
        ) as mock_verify:
            # 4. Execution
            report = self.reconciler.reconcile()

            # 5. Assertion: Verification WAS called
            mock_verify.assert_called_once_with(pos)

            # 6. Assertion: Position was NOT closed
            self.mock_repo.update_position.assert_not_called()

            # 7. Critical issue reported
            assert len(report.critical_issues) > 0
            assert "CRITICAL SYNC ISSUE" in report.critical_issues[0]
            print(
                "[Verification] Verification logic confirmed: Verification called, position NOT closed on failure."
            )

    def test_manual_verification_usage_success(self):
        """
        Verify Fix for Issue #244: Unused Verification Logic.
        If verification succeeds (returns True), position IS closed/updated.
        """
        # 1. Setup: Alpaca empty
        self.mock_alpaca.get_all_positions.return_value = []

        # 2. Setup: Old position
        now = datetime.now(timezone.utc)
        pos = MagicMock(spec=Position)
        pos.symbol = "ETH/USD"
        pos.status = TradeStatus.OPEN
        pos.position_id = "pos-789"
        pos.trade_type = "EXECUTED"
        pos.created_at = now - timedelta(minutes=10)

        self.mock_repo.get_open_positions.return_value = [pos]

        # 3. Mock handle_manual_exit_verification to return True
        # NOTE: The real method updates the position object. Here we just return True.
        with patch.object(
            self.reconciler, "handle_manual_exit_verification", return_value=True
        ) as mock_verify:
            # 4. Execution
            self.reconciler.reconcile()

            # 5. Assertion: Verification WAS called
            mock_verify.assert_called_once_with(pos)

            # 6. Assertion: Position WAS updated
            self.mock_repo.update_position.assert_called_once_with(pos)
            print(
                "[Verification] Verification logic confirmed: Position updated on success."
            )
