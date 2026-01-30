"""Unit tests for the main application entrypoint."""

from contextlib import ExitStack
from datetime import date
from unittest.mock import ANY, MagicMock, Mock, call, patch

import pytest
from crypto_signals.domain.schemas import (
    AssetClass,
    OrderSide,
    Position,
    SignalStatus,
    TradeStatus,
)
from crypto_signals.main import main
from loguru import logger


@pytest.fixture
def caplog(caplog):
    """Override caplog fixture to capture loguru logs."""
    handler_id = logger.add(
        caplog.handler,
        format="{message}",
        level=0,
        filter=lambda record: record["level"].no >= 0,
        catch=False,
    )
    yield caplog
    logger.remove(handler_id)


@pytest.fixture
def mock_dependencies():
    """Mock all external dependencies used in main.py."""
    with ExitStack() as stack:
        stock_client = stack.enter_context(patch("crypto_signals.main.get_stock_data_client"))
        crypto_client = stack.enter_context(patch("crypto_signals.main.get_crypto_data_client"))
        trading_client = stack.enter_context(patch("crypto_signals.main.get_trading_client"))
        market_provider = stack.enter_context(patch("crypto_signals.main.MarketDataProvider"))
        generator = stack.enter_context(patch("crypto_signals.main.SignalGenerator"))
        repo = stack.enter_context(patch("crypto_signals.main.SignalRepository"))
        discord = stack.enter_context(patch("crypto_signals.main.DiscordClient"))
        asset_validator = stack.enter_context(patch("crypto_signals.main.AssetValidationService"))
        mock_settings = stack.enter_context(patch("crypto_signals.main.get_settings"))
        mock_secrets = stack.enter_context(patch("crypto_signals.main.init_secrets", return_value=True))
        mock_firestore_config = stack.enter_context(patch("crypto_signals.main.load_config_from_firestore"))
        position_repo = stack.enter_context(patch("crypto_signals.main.PositionRepository"))
        execution_engine = stack.enter_context(patch("crypto_signals.main.ExecutionEngine"))
        job_lock = stack.enter_context(patch("crypto_signals.main.JobLockRepository"))
        rejected_repo = stack.enter_context(patch("crypto_signals.main.RejectedSignalRepository"))
        trade_archival = stack.enter_context(patch("crypto_signals.main.TradeArchivalPipeline"))
        fee_patch = stack.enter_context(patch("crypto_signals.main.FeePatchPipeline"))
        price_patch = stack.enter_context(patch("crypto_signals.main.PricePatchPipeline"))
        reconciler = stack.enter_context(patch("crypto_signals.main.StateReconciler"))
        job_metadata_repo = stack.enter_context(patch("crypto_signals.main.JobMetadataRepository"))
        rejected_archival = stack.enter_context(
            patch("crypto_signals.main.RejectedSignalArchival")
        )
        expired_archival = stack.enter_context(
            patch("crypto_signals.main.ExpiredSignalArchivalPipeline")
        )

        job_metadata_repo.return_value.get_last_run_date.return_value = None
        # Configure mock settings
        mock_settings.return_value.CRYPTO_SYMBOLS = [
            "BTC/USD",
            "ETH/USD",
            "XRP/USD",
        ]
        # Simulate Basic Plan: Empty equities by default
        mock_settings.return_value.EQUITY_SYMBOLS = []
        mock_settings.return_value.RATE_LIMIT_DELAY = 0.0  # Disable delay for tests
        mock_settings.return_value.ENABLE_GCP_LOGGING = False
        mock_settings.return_value.DISCORD_BOT_TOKEN = "test_token"
        mock_settings.return_value.DISCORD_CHANNEL_ID_CRYPTO = "123"
        mock_settings.return_value.DISCORD_CHANNEL_ID_STOCK = "456"

        # Default: No Firestore config (fallback behavior)
        mock_firestore_config.return_value = {}

        # Configure MarketDataProvider to return non-empty DataFrame by default
        # This prevents main.py from skipping processing due to "No data" check
        # Use side_effect to ensure a fresh clean mock (or consistent one) with empty=False
        def get_daily_bars_side_effect(*args, **kwargs):
            m = MagicMock()
            m.empty = False
            return m

        market_provider.return_value.get_daily_bars.side_effect = (
            get_daily_bars_side_effect
        )

        # Configure AssetValidationService to pass-through all symbols
        # (validation is tested separately in test_asset_service.py)
        def get_valid_portfolio_side_effect(symbols, asset_class):
            return list(symbols)

        asset_validator.return_value.get_valid_portfolio.side_effect = (
            get_valid_portfolio_side_effect
        )

        # Configure JobLock to always succeed
        job_lock.return_value.acquire_lock.return_value = True

        # Configure Discord Thread Recovery to return None by default (not found)
        # This fixes regression in existing tests that don't expect recovery
        discord.return_value.find_thread_by_signal_id.return_value = None

        # Configure Pipeline default returns (int) to avoid TypeError in comparisons
        trade_archival.return_value.run.return_value = 0
        fee_patch.return_value.run.return_value = 0
        price_patch.return_value.run.return_value = 0
        rejected_archival.return_value.run.return_value = 0
        expired_archival.return_value.run.return_value = 0

        yield {
            "stock_client": stock_client,
            "crypto_client": crypto_client,
            "trading_client": trading_client,
            "market_provider": market_provider,
            "generator": generator,
            "repo": repo,
            "discord": discord,
            "asset_validator": asset_validator,
            "settings": mock_settings,
            "secrets": mock_secrets,
            "firestore_config": mock_firestore_config,
            "position_repo": position_repo,
            "execution_engine": execution_engine,
            "job_lock": job_lock,
            "rejected_repo": rejected_repo,
            "trade_archival": trade_archival,
            "fee_patch": fee_patch,
            "price_patch": price_patch,
            "reconciler": reconciler,
            "rejected_archival": rejected_archival,
            "expired_archival": expired_archival,
        }


def test_main_execution_flow(mock_dependencies):
    """Test the normal execution flow of the main function."""
    # Setup mocks
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    # Mock signal generation to return a signal for BTC/USD only
    mock_signal = MagicMock()
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_btc_main"
    mock_signal.pattern_name = "bullish_engulfing"
    mock_signal.suggested_stop = 90000.0
    mock_signal.discord_thread_id = None

    # Ensure find_thread returns None by default (simulate not found)
    mock_discord_instance.find_thread_by_signal_id.return_value = None

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Mock send_signal to return a thread_id
    mock_discord_instance.send_signal.return_value = "thread_123456"

    # Create a manager to track call order across mocks
    manager = Mock()
    manager.attach_mock(mock_repo_instance.save, "save")
    manager.attach_mock(mock_discord_instance.send_signal, "send_signal")
    manager.attach_mock(mock_repo_instance.update_signal, "update_signal")

    # === PIPELINE TRACKING (Issue #149) ===

    # Detach return value to prevent attribute access logs (critical_issues, etc.)
    mock_report = MagicMock()
    mock_report.critical_issues = []
    mock_report.zombies = []
    mock_report.orphans = []
    mock_report.reconciled_count = 0
    mock_dependencies["reconciler"].return_value.reconcile.return_value = mock_report

    # Configure pipeline return values to prevent logging interaction (str/repr calls)
    mock_dependencies["trade_archival"].return_value.run.return_value = 5
    mock_dependencies["fee_patch"].return_value.run.return_value = 2
    mock_dependencies["rejected_archival"].return_value.run.return_value = 3
    mock_dependencies["expired_archival"].return_value.run.return_value = 4

    # Setup tracking for Reconcile -> Archive -> Fee Patch Sequence
    pipeline_manager = Mock()
    pipeline_manager.attach_mock(
        mock_dependencies["reconciler"].return_value.reconcile, "reconcile"
    )
    pipeline_manager.attach_mock(
        mock_dependencies["trade_archival"].return_value.run, "archive"
    )
    pipeline_manager.attach_mock(
        mock_dependencies["rejected_archival"].return_value.run, "rejected_archive"
    )
    pipeline_manager.attach_mock(
        mock_dependencies["expired_archival"].return_value.run, "expired_archive"
    )
    pipeline_manager.attach_mock(
        mock_dependencies["fee_patch"].return_value.run, "fee_patch"
    )

    # Execute
    main(smoke_test=False)

    # Verify Initialization
    mock_dependencies["stock_client"].assert_called_once()
    mock_dependencies["crypto_client"].assert_called_once()
    mock_dependencies["market_provider"].assert_called_once()
    mock_dependencies["generator"].assert_called_once()
    mock_dependencies["repo"].assert_called_once()
    mock_dependencies["discord"].assert_called_once()

    # Verify Thread Recovery Attempted
    # find_thread_by_signal_id should be called before send_signal
    mock_discord_instance.find_thread_by_signal_id.assert_called()

    # Verify Portfolio Iteration & Asset Class Detection
    expected_calls = [
        call("BTC/USD", AssetClass.CRYPTO, dataframe=ANY),
        call("ETH/USD", AssetClass.CRYPTO, dataframe=ANY),
        call("XRP/USD", AssetClass.CRYPTO, dataframe=ANY),
    ]
    mock_gen_instance.generate_signals.assert_has_calls(expected_calls, any_order=False)

    # Verify Signal Handling (Save FIRST with CREATED, then Discord, then Update to WAITING)
    # Should be called once for BTC/USD
    mock_repo_instance.save.assert_called_once_with(mock_signal)
    mock_discord_instance.send_signal.assert_called_once_with(mock_signal)
    mock_repo_instance.update_signal_atomic.assert_called()

    # Verify thread_id was attached to signal after Discord notification
    assert mock_signal.discord_thread_id == "thread_123456"

    # Verify explicit call order: Save -> Discord -> Update (two-phase commit)
    # update_signal_atomic args: signal_id, updates dict
    expected_updates = {
        "discord_thread_id": "thread_123456",
        "status": SignalStatus.WAITING.value,
    }

    # We can't easily check dictionary equality inside assert_has_calls with objects unless we use ANY for specific fields
    # But usually atomic update is called instead of legacy update_signal
    mock_repo_instance.update_signal_atomic.assert_called_with(
        mock_signal.signal_id, expected_updates
    )

    # Legacy update should NOT be called
    mock_repo_instance.update_signal.assert_not_called()

    # Verify precise call order (Names only to avoid fragile call object comparison)
    actual_calls = [c[0] for c in pipeline_manager.mock_calls]
    assert actual_calls == [
        "reconcile",
        "archive",
        "rejected_archive",
        "expired_archive",
        "fee_patch",
    ], f"Actual calls mismatch: {actual_calls}"


def test_send_signal_captures_thread_id(mock_dependencies):
    """Test that thread_id from send_signal is captured and persisted."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    # Setup signal with required attributes for structured logging
    mock_signal = MagicMock()
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_btc"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0
    mock_signal.asset_class = AssetClass.CRYPTO

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Mock send_signal to return a thread_id
    mock_discord_instance.send_signal.return_value = "mock_thread_98765"

    # Mock recovery to return None (not found) implies send_signal will be called
    mock_discord_instance.find_thread_by_signal_id.return_value = None

    # Execute
    main(smoke_test=False)

    # Verify thread_id was attached to signal
    assert mock_signal.discord_thread_id == "mock_thread_98765"

    # Verify explicit interactions
    mock_repo_instance.save.assert_called()
    mock_discord_instance.send_signal.assert_called()
    mock_repo_instance.update_signal_atomic.assert_called()
    mock_repo_instance.update_signal.assert_not_called()


def test_main_symbol_error_handling(mock_dependencies):
    """Test that main continues processing remaining symbols if one fails."""
    mock_gen_instance = mock_dependencies["generator"].return_value

    # Make ETH/USD raise an exception
    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "ETH/USD":
            raise ValueError("Simulated Analysis Error")
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Execute (should not raise exception)
    main(smoke_test=False)

    # Verify that subsequent symbols (e.g., XRP/USD) were still processed
    calls = mock_gen_instance.generate_signals.call_args_list
    symbols_processed = [args[0] for args, _ in calls]

    assert "BTC/USD" in symbols_processed
    assert "ETH/USD" in symbols_processed
    assert "XRP/USD" in symbols_processed


def test_main_fatal_error():
    """Test that critical initialization errors cause a system exit."""
    with patch("crypto_signals.main.get_stock_data_client") as mock_init:
        mock_init.side_effect = ImportError("Critical Dependency Missing")

        with pytest.raises(SystemExit) as excinfo:
            main(smoke_test=False)

        assert excinfo.value.code == 1


def test_main_notification_failure(mock_dependencies, caplog):
    """Test that main logs a warning if notification fails."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    # Setup signal for BTC/USD only
    mock_signal = MagicMock()
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_notification"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0
    mock_signal.asset_class = AssetClass.CRYPTO

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Mock notification failure
    mock_discord_instance.send_signal.return_value = False

    # Execute with caplog capturing (handled by fixture)

    with caplog.at_level("WARNING"):
        main(smoke_test=False)

    # Verify warning (now uses compensation logic - signal marked invalid)
    assert "Discord notification failed" in caplog.text
    assert "marking signal as invalidated" in caplog.text


def test_main_repo_failure(mock_dependencies, caplog):
    """Test that main logs an error and continues if repository save fails."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value

    # Setup signals with proper signal_id
    def gen_side_effect(symbol, asset_class, **kwargs):
        if symbol in ["BTC/USD", "ETH/USD"]:
            sig = MagicMock()
            sig.symbol = symbol
            sig.signal_id = f"test_id_{symbol.replace('/', '_')}"
            sig.pattern_name = "test_pattern"
            sig.suggested_stop = 100.0
            sig.asset_class = AssetClass.CRYPTO
            return sig
        return None

    mock_gen_instance.generate_signals.side_effect = gen_side_effect

    # Mock repository failure ONLY for BTC/USD
    def save_side_effect(signal):
        if signal.symbol == "BTC/USD":
            raise RuntimeError("Firestore Unavailable")
        return None

    mock_repo_instance.save.side_effect = save_side_effect

    # Execute with caplog capturing (handled by fixture)

    with caplog.at_level("ERROR"):
        main(smoke_test=False)

    # Verify error log for persistence failure (new behavior: skips notification)
    assert "Failed to persist signal" in caplog.text
    assert "skipping notification to prevent zombie signal" in caplog.text

    # Verify that ETH/USD was still processed (Loop continued)
    calls = mock_gen_instance.generate_signals.call_args_list
    symbols_processed = [args[0] for args, _ in calls]
    assert "ETH/USD" in symbols_processed


def test_main_uses_firestore_config(mock_dependencies):
    """Test that Firestore configuration overrides .env settings."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_firestore_config = mock_dependencies["firestore_config"]
    mock_settings = mock_dependencies["settings"].return_value

    # Setup Firestore returns
    mock_firestore_config.return_value = {
        "CRYPTO_SYMBOLS": ["SOL/USD"],
        # NOTE: Equities intentionally omitted in this test to verify simple crypto override
    }

    # Mock signal generation to avoid side effects
    mock_gen_instance.generate_signals.return_value = None

    # Execute
    main(smoke_test=False)

    # Verify Logic
    # 1. Check if settings were updated
    assert mock_settings.CRYPTO_SYMBOLS == ["SOL/USD"]

    # 2. Verify iteration happened on NEW symbols
    expected_calls = [
        call("SOL/USD", AssetClass.CRYPTO, dataframe=ANY),
    ]
    mock_gen_instance.generate_signals.assert_has_calls(expected_calls, any_order=True)

    # 3. Ensure OLD symbols were NOT processed
    assert mock_gen_instance.generate_signals.call_count == 1


def test_main_fallback_to_env_on_empty(mock_dependencies):
    """Test fallback to .env when Firestore returns empty config."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_firestore_config = mock_dependencies["firestore_config"]
    mock_settings = mock_dependencies["settings"].return_value

    # Setup Firestore returns empty
    mock_firestore_config.return_value = {}

    # Mock signal generation
    mock_gen_instance.generate_signals.return_value = None

    # Execute
    main(smoke_test=False)

    # Verify Logic
    # Settings should remain as default (from fixture)
    assert mock_settings.CRYPTO_SYMBOLS == ["BTC/USD", "ETH/USD", "XRP/USD"]

    # Should process default symbols
    mock_gen_instance.generate_signals.assert_any_call(
        "BTC/USD", AssetClass.CRYPTO, dataframe=ANY
    )


def test_guardrail_ignores_firestore_equities(mock_dependencies, caplog):
    """
    Risk Verification: Ensure that if Firestore returns equities,
    the system respects the hardcoded restriction and IGNORES them.
    """
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_firestore_config = mock_dependencies["firestore_config"]
    mock_settings = mock_dependencies["settings"].return_value

    # 1. Simulate Firestore returning Equities
    mock_firestore_config.return_value = {
        "CRYPTO_SYMBOLS": ["BTC/USD"],
        "EQUITY_SYMBOLS": ["AAPL", "TSLA"],
    }

    # 2. Simulate "Basic Plan" Restriction (default is empty)
    mock_settings.EQUITY_SYMBOLS = []

    mock_gen_instance.generate_signals.return_value = None

    mock_gen_instance.generate_signals.return_value = None

    with caplog.at_level("WARNING"):
        main(smoke_test=False)

    # Asset: Equities should still be EMPTY because the guardrail ignored them.
    assert mock_settings.EQUITY_SYMBOLS == []

    # Verify equities were NOT processed
    calls = mock_gen_instance.generate_signals.call_args_list
    symbols = [args[0] for args, _ in calls]
    assert "AAPL" not in symbols
    assert "TSLA" not in symbols
    assert "BTC/USD" in symbols


# =============================================================================
# POSITION SYNC LOOP TESTS
# =============================================================================


def _create_test_position(
    position_id="pos-1",
    status=TradeStatus.OPEN,
    tp_order_id=None,
    sl_order_id=None,
    filled_at=None,
    entry_fill_price=50000.0,
    failed_reason=None,
):
    """Helper to create a Position for testing."""
    return Position(
        position_id=position_id,
        ds=date(2025, 1, 15),
        account_id="paper",
        symbol="BTC/USD",
        signal_id="signal-1",
        alpaca_order_id="alpaca-order-1",
        status=status,
        entry_fill_price=entry_fill_price,
        current_stop_loss=48000.0,
        qty=0.05,
        side=OrderSide.BUY,
        tp_order_id=tp_order_id,
        sl_order_id=sl_order_id,
        filled_at=filled_at,
        failed_reason=failed_reason,
    )


def test_sync_loop_updates_position_on_status_change(mock_dependencies, caplog):
    """Test that positions are updated when status changes (TP/SL hit)."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_gen_instance.generate_signals.return_value = None

    mock_settings = mock_dependencies["settings"].return_value
    mock_settings.ENABLE_EXECUTION = True

    mock_position_repo = mock_dependencies["position_repo"].return_value
    mock_execution_engine = mock_dependencies["execution_engine"].return_value

    # Create position that will be "closed" by sync
    original_pos = _create_test_position(status=TradeStatus.OPEN)
    closed_pos = _create_test_position(status=TradeStatus.CLOSED)

    mock_position_repo.get_open_positions.return_value = [original_pos]
    mock_execution_engine.sync_position_status.return_value = closed_pos

    with caplog.at_level("INFO"):
        main(smoke_test=False)

    # Verify update was called with closed status
    mock_position_repo.update_position.assert_called_once_with(closed_pos)

    # Verify logging
    assert "Position pos-1 closed: CLOSED" in caplog.text


def test_sync_loop_updates_position_on_leg_id_change(mock_dependencies, caplog):
    """Test that positions are updated when TP/SL leg IDs change."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_gen_instance.generate_signals.return_value = None

    mock_settings = mock_dependencies["settings"].return_value
    mock_settings.ENABLE_EXECUTION = True

    mock_position_repo = mock_dependencies["position_repo"].return_value
    mock_execution_engine = mock_dependencies["execution_engine"].return_value

    # Create position without leg IDs
    original_pos = _create_test_position(tp_order_id=None, sl_order_id=None)
    # Sync returns position with leg IDs populated
    synced_pos = _create_test_position(tp_order_id="tp-leg-123", sl_order_id="sl-leg-456")

    mock_position_repo.get_open_positions.return_value = [original_pos]
    mock_execution_engine.sync_position_status.return_value = synced_pos

    with caplog.at_level("INFO"):
        main(smoke_test=False)

    # Verify update was called
    mock_position_repo.update_position.assert_called_once_with(synced_pos)

    # Verify logging shows what changed
    assert "Position pos-1 synced" in caplog.text
    assert "TP=tp-leg-123" in caplog.text
    assert "SL=sl-leg-456" in caplog.text


def test_sync_loop_handles_exceptions_gracefully(mock_dependencies, caplog):
    """Test that sync loop continues after individual position sync failures."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_gen_instance.generate_signals.return_value = None

    mock_settings = mock_dependencies["settings"].return_value
    mock_settings.ENABLE_EXECUTION = True

    mock_position_repo = mock_dependencies["position_repo"].return_value
    mock_execution_engine = mock_dependencies["execution_engine"].return_value

    # Create two positions
    pos1 = _create_test_position(position_id="pos-1")
    pos2 = _create_test_position(position_id="pos-2")

    mock_position_repo.get_open_positions.return_value = [pos1, pos2]

    # First position sync fails, second succeeds with changes
    synced_pos2 = _create_test_position(position_id="pos-2", tp_order_id="tp-new")

    def sync_side_effect(pos):
        if pos.position_id == "pos-1":
            raise RuntimeError("Alpaca API Error")
        return synced_pos2

    mock_execution_engine.sync_position_status.side_effect = sync_side_effect

    with caplog.at_level("WARNING"):
        main(smoke_test=False)

    # Verify error was logged for pos-1
    assert "Failed to sync position pos-1" in caplog.text
    assert "Alpaca API Error" in caplog.text

    # Verify pos-2 was still updated (loop continued)
    mock_position_repo.update_position.assert_called_once_with(synced_pos2)


def test_sync_loop_skipped_when_execution_disabled(mock_dependencies):
    """Test that sync loop is skipped when ENABLE_EXECUTION is False."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_gen_instance.generate_signals.return_value = None

    mock_settings = mock_dependencies["settings"].return_value
    mock_settings.ENABLE_EXECUTION = False

    mock_position_repo = mock_dependencies["position_repo"].return_value

    main(smoke_test=False)

    # Verify get_open_positions was never called
    mock_position_repo.get_open_positions.assert_not_called()


def test_sync_loop_no_update_when_position_unchanged(mock_dependencies):
    """Test that positions are not updated when nothing changed."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_gen_instance.generate_signals.return_value = None

    mock_settings = mock_dependencies["settings"].return_value
    mock_settings.ENABLE_EXECUTION = True

    mock_position_repo = mock_dependencies["position_repo"].return_value
    mock_execution_engine = mock_dependencies["execution_engine"].return_value

    # Create position
    pos = _create_test_position()

    mock_position_repo.get_open_positions.return_value = [pos]
    # Sync returns same position (no changes)
    mock_execution_engine.sync_position_status.return_value = pos

    main(smoke_test=False)

    # Verify update was NOT called
    mock_position_repo.update_position.assert_not_called()


# =============================================================================
# ZOMBIE SIGNAL PREVENTION TESTS
# =============================================================================


def test_zombie_signal_prevention_persistence_first(mock_dependencies):
    """
    Test that signals are persisted BEFORE Discord notification (two-phase commit).

    This prevents "Zombie Signals" where users receive Discord notifications
    for signals that were never persisted to the database.
    """
    from crypto_signals.domain.schemas import SignalStatus

    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    # Setup signal
    mock_signal = MagicMock()
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_zombie_prevention"
    mock_signal.pattern_name = "bullish_engulfing"
    mock_signal.suggested_stop = 90000.0

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect
    mock_discord_instance.send_signal.return_value = "thread_123"

    # Track call order
    call_order = []

    def track_save(signal):
        call_order.append(("save", signal.status))

    def track_update(signal):
        call_order.append(("update", signal.status))

    def track_discord(signal):
        call_order.append(("discord", getattr(signal, "status", None)))
        return "thread_123"

    mock_discord_instance.send_signal.side_effect = track_discord
    mock_repo_instance.save.side_effect = track_save

    def track_atomic(signal_id, updates):
        # Interpret status from updates dict
        status = updates.get("status")
        # Convert value back to enum if necessary or just store value
        # Tests check against SignalStatus enum usually, so let's try to map back if int?
        # But wait, updates["status"] is .value (int/str). SignalStatus is Enum.
        # Original test tracked signal.status (Enum).
        # Let's just track ("update", status_value) and adjust assertion.
        call_order.append(("update", status))
        return True

    mock_repo_instance.update_signal_atomic.side_effect = track_atomic

    main(smoke_test=False)

    # Verify CREATED status set first, then saved, then Discord, then WAITING update
    assert len(call_order) == 3
    assert call_order[0] == ("save", SignalStatus.CREATED)
    assert call_order[1][0] == "discord"  # Discord called after save
    # Atomic update passes the VALUE of the status, verify that.
    assert call_order[2] == ("update", SignalStatus.WAITING.value)

    # Verify atomic update called separately
    mock_repo_instance.update_signal_atomic.assert_called()


def test_zombie_signal_compensation_on_discord_failure(mock_dependencies, caplog):
    """
    Test that signal is marked INVALIDATED if Discord notification fails.

    When persistence succeeds but Discord fails, we compensate by marking
    the signal as INVALIDATED to prevent untracked active signals.
    """
    from crypto_signals.domain.schemas import ExitReason, SignalStatus

    mock_gen_instance = mock_dependencies["generator"].return_value
    _mock_repo_instance = mock_dependencies["repo"].return_value  # noqa: F841
    mock_discord_instance = mock_dependencies["discord"].return_value

    mock_signal = MagicMock()
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_discord_fail"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0
    mock_signal.asset_class = AssetClass.CRYPTO

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Discord fails - returns None/False
    mock_discord_instance.send_signal.return_value = None

    with caplog.at_level("WARNING"):
        main(smoke_test=False)

    # Verify compensation: signal marked as INVALIDATED via atomic update
    if not mock_dependencies["repo"].return_value.update_signal_atomic.called:
        pytest.fail(f"Atomic update NOT called. Logs:\n{caplog.text}")

    # We check the atomic update call args because checking mock_signal.status can be unreliable if main uses a copy
    args, _ = mock_dependencies["repo"].return_value.update_signal_atomic.call_args
    assert args[0] == "test_signal_discord_fail"
    updates = args[1]
    assert updates["status"] == SignalStatus.INVALIDATED
    assert updates["exit_reason"] == ExitReason.NOTIFICATION_FAILED

    # Verify warning was logged
    assert "Discord notification failed" in caplog.text
    assert "marking signal as invalidated" in caplog.text


def test_signal_skipped_if_initial_persistence_fails(mock_dependencies, caplog):
    """
    Test that Discord is NOT called if initial persistence fails.

    This is critical to prevent Zombie Signals - if we can't persist,
    we must NOT notify users about a signal we can't track.
    """
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    mock_signal = MagicMock()
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_persist_fail"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0
    mock_signal.asset_class = AssetClass.CRYPTO

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Initial save fails
    mock_repo_instance.save.side_effect = RuntimeError("Firestore Unavailable")

    with caplog.at_level("ERROR"):
        main(smoke_test=False)

    # Verify Discord was NEVER called (zombie prevention)
    mock_discord_instance.send_signal.assert_not_called()

    # Verify error logged
    assert "Failed to persist signal" in caplog.text
    assert "skipping notification to prevent zombie signal" in caplog.text


def test_thread_recovery_check(mock_dependencies, caplog):
    """Test that existing thread is recovered and send_signal is skipped."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value

    # Setup signal
    # Setup signal
    mock_signal = MagicMock()
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_recovery"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.asset_class = AssetClass.CRYPTO
    mock_signal.discord_thread_id = None  # Initially missing

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Reinforce environment mocks
    mock_dependencies["job_lock"].return_value.acquire_lock.return_value = True
    mock_dependencies["secrets"].return_value = True

    # Mock Recovery Success
    mock_discord_instance.find_thread_by_signal_id.return_value = "recovered_thread_123"
    mock_repo_instance.update_signal_atomic.return_value = True

    with caplog.at_level("INFO"):
        main(smoke_test=False)

    # Verify:
    # 1. find_thread called
    mock_discord_instance.find_thread_by_signal_id.assert_called_once()

    # 2. send_signal SKIPPED
    mock_discord_instance.send_signal.assert_not_called()

    # 3. Verify object update explicitly if logical check needed
    assert mock_signal.discord_thread_id == "recovered_thread_123"

    # 3. repo updated with recovered ID
    # atomic update call
    mock_repo_instance.update_signal_atomic.assert_called()
    # Check signal object state updated
    assert mock_signal.discord_thread_id == "recovered_thread_123"
