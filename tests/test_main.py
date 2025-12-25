"""Unit tests for the main application entrypoint."""

from datetime import date
from unittest.mock import ANY, MagicMock, Mock, call, patch

import pytest
from crypto_signals.domain.schemas import (
    AssetClass,
    OrderSide,
    Position,
    Signal,
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
    with (
        patch("crypto_signals.main.get_stock_data_client") as stock_client,
        patch("crypto_signals.main.get_crypto_data_client") as crypto_client,
        patch("crypto_signals.main.get_trading_client") as trading_client,
        patch("crypto_signals.main.MarketDataProvider") as market_provider,
        patch("crypto_signals.main.SignalGenerator") as generator,
        patch("crypto_signals.main.SignalRepository") as repo,
        patch("crypto_signals.main.DiscordClient") as discord,
        patch("crypto_signals.main.AssetValidationService") as asset_validator,
        patch("crypto_signals.main.get_settings") as mock_settings,
        patch("crypto_signals.main.init_secrets", return_value=True) as mock_secrets,
        patch("crypto_signals.main.load_config_from_firestore") as mock_firestore_config,
        patch("crypto_signals.main.PositionRepository") as position_repo,
        patch("crypto_signals.main.ExecutionEngine") as execution_engine,
    ):
        # Configure mock settings
        mock_settings.return_value.CRYPTO_SYMBOLS = [
            "BTC/USD",
            "ETH/USD",
            "XRP/USD",
        ]
        # Simulate Basic Plan: Empty equities by default
        mock_settings.return_value.EQUITY_SYMBOLS = []

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
        }


def test_main_execution_flow(mock_dependencies):
    """Test the normal execution flow of the main function."""
    # Setup mocks
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    # Mock signal generation to return a signal for BTC/USD only
    mock_signal = MagicMock(spec=Signal)
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_btc_main"
    mock_signal.pattern_name = "bullish_engulfing"
    mock_signal.suggested_stop = 90000.0

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

    # Execute
    main()

    # Verify Initialization
    mock_dependencies["stock_client"].assert_called_once()
    mock_dependencies["crypto_client"].assert_called_once()
    mock_dependencies["market_provider"].assert_called_once()
    mock_dependencies["generator"].assert_called_once()
    mock_dependencies["repo"].assert_called_once()
    mock_dependencies["discord"].assert_called_once()

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
    mock_repo_instance.update_signal.assert_called_once_with(mock_signal)

    # Verify thread_id was attached to signal after Discord notification
    assert mock_signal.discord_thread_id == "thread_123456"

    # Verify explicit call order: Save -> Discord -> Update (two-phase commit)
    expected_call_order = [
        call.save(mock_signal),
        call.send_signal(mock_signal),
        call.update_signal(mock_signal),
    ]
    assert manager.mock_calls == expected_call_order


def test_send_signal_captures_thread_id(mock_dependencies):
    """Test that thread_id from send_signal is captured and persisted."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    # Setup signal with required attributes for structured logging
    mock_signal = MagicMock(spec=Signal)
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_btc"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Mock send_signal to return a thread_id
    mock_discord_instance.send_signal.return_value = "mock_thread_98765"

    # Create a manager to track call order across mocks
    manager = Mock()
    manager.attach_mock(mock_repo_instance.save, "save")
    manager.attach_mock(mock_discord_instance.send_signal, "send_signal")
    manager.attach_mock(mock_repo_instance.update_signal, "update_signal")

    # Execute
    main()

    # Verify thread_id was attached to signal
    assert mock_signal.discord_thread_id == "mock_thread_98765"

    # Verify explicit call order: Save -> Discord -> Update (two-phase commit)
    expected_call_order = [
        call.save(mock_signal),
        call.send_signal(mock_signal),
        call.update_signal(mock_signal),
    ]
    assert manager.mock_calls == expected_call_order


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
    main()

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
            main()

        assert excinfo.value.code == 1


def test_main_notification_failure(mock_dependencies, caplog):
    """Test that main logs a warning if notification fails."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    # Setup signal for BTC/USD only
    mock_signal = MagicMock(spec=Signal)
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_notification"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Mock notification failure
    mock_discord_instance.send_signal.return_value = False

    # Execute with caplog capturing (handled by fixture)

    with caplog.at_level("WARNING"):
        main()

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
            sig = MagicMock(spec=Signal)
            sig.symbol = symbol
            sig.signal_id = f"test_id_{symbol.replace('/', '_')}"
            sig.pattern_name = "test_pattern"
            sig.suggested_stop = 100.0
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
        main()

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
    main()

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
    main()

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
        main()

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
        main()

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
        main()

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
        main()

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

    main()

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

    main()

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
    mock_signal = MagicMock(spec=Signal)
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

    mock_repo_instance.save.side_effect = track_save
    mock_repo_instance.update_signal.side_effect = track_update
    mock_discord_instance.send_signal.side_effect = track_discord

    main()

    # Verify CREATED status set first, then saved, then Discord, then WAITING update
    assert len(call_order) == 3
    assert call_order[0] == ("save", SignalStatus.CREATED)
    assert call_order[1][0] == "discord"  # Discord called after save
    assert call_order[2] == ("update", SignalStatus.WAITING)


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

    mock_signal = MagicMock(spec=Signal)
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_discord_fail"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Discord fails - returns None/False
    mock_discord_instance.send_signal.return_value = None

    with caplog.at_level("WARNING"):
        main()

    # Verify compensation: signal marked as INVALIDATED
    assert mock_signal.status == SignalStatus.INVALIDATED
    assert mock_signal.exit_reason == ExitReason.NOTIFICATION_FAILED

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

    mock_signal = MagicMock(spec=Signal)
    mock_signal.symbol = "BTC/USD"
    mock_signal.signal_id = "test_signal_persist_fail"
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Initial save fails
    mock_repo_instance.save.side_effect = RuntimeError("Firestore Unavailable")

    with caplog.at_level("ERROR"):
        main()

    # Verify Discord was NEVER called (zombie prevention)
    mock_discord_instance.send_signal.assert_not_called()

    # Verify error logged
    assert "Failed to persist signal" in caplog.text
    assert "skipping notification to prevent zombie signal" in caplog.text
