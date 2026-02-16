"""Unit tests for the StateReconciler module."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.domain.schemas import (
    ExitReason,
    OrderSide,
    Position,
    TradeStatus,
    TradeType,
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
    mock.CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD"]
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
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


@pytest.fixture
def sample_alpaca_position():
    """Create a sample Alpaca position object."""
    mock_pos = MagicMock()
    # Alpaca uses symbols without slashes for crypto (e.g., BTCUSD)
    mock_pos.symbol = "BTCUSD"
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
        pos1.created_at = datetime.now(timezone.utc) - timedelta(hours=1)

        pos2 = MagicMock(spec=Position)
        pos2.symbol = "ETH/USD"
        pos2.status = TradeStatus.OPEN
        pos2.position_id = "signal-2"
        pos2.trade_type = "EXECUTED"
        pos2.created_at = datetime.now(timezone.utc) - timedelta(hours=1)

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
        pos1.symbol = "BTCUSD"

        pos2 = MagicMock()
        pos2.symbol = "ETHUSD"

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


class TestReconcilerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_reconcile_with_empty_symbols(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """Reconciliation handles empty symbol sets gracefully."""
        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
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
        mock_discord_client,
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
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        # Should still return report with critical issues
        report = reconciler.reconcile()

        assert len(report.critical_issues) > 0
        assert "BTC/USD" in report.zombies  # Zombie still detected

    def test_reconcile_discord_notification_failure_not_blocking(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_alpaca_position,
    ):
        """Discord notification failure doesn't block reconciliation."""
        mock_trading_client.get_all_positions.return_value = [sample_alpaca_position]
        mock_position_repo.get_open_positions.return_value = []

        # Fail on Discord send
        mock_discord_client.send_message.side_effect = Exception("Discord Error")

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        # Should still return report
        report = reconciler.reconcile()

        assert len(report.orphans) > 0  # Orphan still detected

        # Check for substring match instead of exact string
        assert any(
            "ORPHAN_POSITION: BTC/USD" in issue for issue in report.critical_issues
        )

    def test_reconcile_report_timestamp_is_set(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
    ):
        """Reconciliation report includes current timestamp."""
        from datetime import datetime

        mock_trading_client.get_all_positions.return_value = []
        mock_position_repo.get_open_positions.return_value = []

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
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
        mock_discord_client,
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
            discord_client=mock_discord_client,
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
        mock_discord_client,
        mock_settings,
        sample_open_position,
    ):
        """Reconciliation detects no issues when symbols match."""
        alpaca_pos = MagicMock()
        alpaca_pos.symbol = "BTCUSD"

        # Use sample_open_position which has all required attributes
        sample_open_position.status = TradeStatus.OPEN
        mock_trading_client.get_all_positions.return_value = [alpaca_pos]
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
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
        mock_discord_client,
    ):
        """Reconciler uses provided settings instead of global defaults."""
        custom_settings = MagicMock()
        custom_settings.ENVIRONMENT = "STAGING"

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=custom_settings,
        )

        assert reconciler.settings == custom_settings
        assert reconciler.settings.ENVIRONMENT == "STAGING"

    def test_reconcile_defaults_to_get_settings_when_none(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
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
                discord_client=mock_discord_client,
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
        mock_discord_client,
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
            discord_client=mock_discord_client,
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
        mock_discord_client,
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
            discord_client=mock_discord_client,
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
        assert any("ZOMBIE_EXIT_GAP" in i for i in report.critical_issues)

        # Should alert Discord
        assert mock_discord_client.send_message.called


class TestReconcilerRaceConditions:
    """Test race condition fixes (Issue #244)."""

    def test_race_condition_zombie_kill(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_open_position,
    ):
        """
        Verify that a 'zombie' which is just a few seconds old is NOT killed/closed.
        This simulates the race condition where `main.py` creates a position,
        saves to DB, submits to Alpaca, but Alpaca hasn't indexed it yet
        when Reconciler runs.
        """
        # 1. Setup: Zombie Position (Open in DB, Missing in Alpaca)
        mock_trading_client.get_all_positions.return_value = []

        # 2. Make it "Young" (created 1 minute ago)
        # Using a fixed time for stability
        now = datetime.now(timezone.utc)
        sample_open_position.created_at = now - timedelta(minutes=1)
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        # 3. Execute with default 5 min grace period
        report = reconciler.reconcile(min_age_minutes=5)

        # 4. Assertions
        # Should NOT be healed/closed
        mock_position_repo.update_position.assert_not_called()

        # Should NOT be in critical issues (it's skipped intentionally)
        assert len(report.critical_issues) == 0

        # Should be in zombies list but skipped
        assert "BTC/USD" in report.zombies

    def test_manual_exit_verification_used(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        sample_open_position,
    ):
        """
        Verify that before closing a zombie, the reconciler calls
        handle_manual_exit_verification.
        """
        # 1. Setup: Old Zombie (valid age)
        mock_trading_client.get_all_positions.return_value = []
        sample_open_position.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_position_repo.get_open_positions.return_value = [sample_open_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        # 2. Mock verification (return True to allow close)
        with patch.object(
            reconciler, "handle_manual_exit_verification", return_value=True
        ) as mock_verify:
            reconciler.reconcile()

            # 3. Verify it was called
            mock_verify.assert_called_once()
            # And position was updated (closed)
            mock_position_repo.update_position.assert_called()


class TestTheoreticalPositions:
    """Test handling of theoretical positions."""

    @pytest.fixture
    def theoretical_position(self):
        return Position(
            position_id="theo-123",
            ds=date(2025, 1, 15),
            account_id="theoretical",
            symbol="BTC/USD",
            signal_id="sig-123",
            alpaca_order_id="theo-order-1",
            status=TradeStatus.OPEN,
            entry_fill_price=50000.0,
            current_stop_loss=48000.0,
            qty=0.01,
            side=OrderSide.BUY,
            trade_type=TradeType.THEORETICAL.value,  # Key field
        )

    def test_reconcile_ignores_theoretical_positions(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        theoretical_position,
    ):
        """Verify that OPEN theoretical positions are NOT flagged as zombies when missing from Alpaca."""
        # Alpaca has NO positions (empty)
        mock_trading_client.get_all_positions.return_value = []

        # Firestore has one OPEN theoretical position
        mock_position_repo.get_open_positions.return_value = [theoretical_position]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        # Should be NO zombies because theoretical trades are filtered out
        assert len(report.zombies) == 0
        assert "BTC/USD" not in report.zombies

        # Should be NO orphans
        assert len(report.orphans) == 0

    def test_reconcile_detects_normal_zombies(
        self,
        mock_trading_client,
        mock_position_repo,
        mock_discord_client,
        mock_settings,
        theoretical_position,
    ):
        """Verify that normal OPEN positions ARE flagged as zombies, even if mixed with theoreticals."""
        # Create a normal executed position
        normal_position = Position(
            position_id="real-123",
            ds=date(2025, 1, 15),
            account_id="paper",
            symbol="ETH/USD",
            signal_id="sig-456",
            alpaca_order_id="alpaca-order-1",
            status=TradeStatus.OPEN,
            entry_fill_price=2000.0,
            current_stop_loss=1900.0,
            qty=1.0,
            side=OrderSide.BUY,
            trade_type=TradeType.EXECUTED.value,  # Normal trade
        )

        # Alpaca has NO positions
        mock_trading_client.get_all_positions.return_value = []

        # Firestore has one THEORETICAL and one NORMAL position
        mock_position_repo.get_open_positions.return_value = [
            theoretical_position,
            normal_position,
        ]

        reconciler = StateReconciler(
            alpaca_client=mock_trading_client,
            position_repo=mock_position_repo,
            discord_client=mock_discord_client,
            settings=mock_settings,
        )

        report = reconciler.reconcile()

        # The normal position should be a zombie
        assert len(report.zombies) == 1
        assert "ETH/USD" in report.zombies

        # The theoretical position (BTC/USD) should be ignored
        assert "BTC/USD" not in report.zombies
