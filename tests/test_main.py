"""Unit tests for the main application entrypoint."""

from unittest.mock import ANY, MagicMock, Mock, call, patch

import pytest
from crypto_signals.domain.schemas import AssetClass, Signal
from crypto_signals.main import main


@pytest.fixture
def mock_dependencies():
    """Mock all external dependencies used in main.py."""
    with (
        patch("crypto_signals.main.get_stock_data_client") as stock_client,
        patch("crypto_signals.main.get_crypto_data_client") as crypto_client,
        patch("crypto_signals.main.MarketDataProvider") as market_provider,
        patch("crypto_signals.main.SignalGenerator") as generator,
        patch("crypto_signals.main.SignalRepository") as repo,
        patch("crypto_signals.main.DiscordClient") as discord,
        patch("crypto_signals.main.get_settings") as mock_settings,
        patch("crypto_signals.main.init_secrets", return_value=True) as mock_secrets,
        patch("crypto_signals.main.load_config_from_firestore") as mock_firestore_config,
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

        yield {
            "stock_client": stock_client,
            "crypto_client": crypto_client,
            "market_provider": market_provider,
            "generator": generator,
            "repo": repo,
            "discord": discord,
            "settings": mock_settings,
            "secrets": mock_secrets,
            "firestore_config": mock_firestore_config,
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
    manager.attach_mock(mock_discord_instance.send_signal, 'send_signal')
    manager.attach_mock(mock_repo_instance.save, 'save')

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
    # Verify Portfolio Iteration & Asset Class Detection
    expected_calls = [
        call("BTC/USD", AssetClass.CRYPTO, dataframe=ANY),
        call("ETH/USD", AssetClass.CRYPTO, dataframe=ANY),
        call("XRP/USD", AssetClass.CRYPTO, dataframe=ANY),
        # Note: Equities are NOT tested here because fixture defaults to empty
    ]
    mock_gen_instance.generate_signals.assert_has_calls(expected_calls, any_order=False)

    # Verify Signal Handling (Send Discord FIRST, then Save)
    # Should be called once for BTC/USD
    mock_discord_instance.send_signal.assert_called_once_with(mock_signal)
    mock_repo_instance.save.assert_called_once_with(mock_signal)

    # Verify thread_id was attached to signal before save
    assert mock_signal.discord_thread_id == "thread_123456"

    # Verify explicit call order: Discord notification MUST happen before Firestore save
    # This ensures thread_id is captured before persistence
    expected_call_order = [
        call.send_signal(mock_signal),
        call.save(mock_signal),
    ]
    assert manager.mock_calls == expected_call_order


def test_send_signal_captures_thread_id(mock_dependencies):
    """Test that thread_id from send_signal is captured and persisted."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value
    mock_discord_instance = mock_dependencies["discord"].return_value

    # Setup signal
    mock_signal = MagicMock(spec=Signal)
    mock_signal.symbol = "BTC/USD"
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
    manager.attach_mock(mock_discord_instance.send_signal, 'send_signal')
    manager.attach_mock(mock_repo_instance.save, 'save')

    # Execute
    main()

    # Verify thread_id was attached to signal
    assert mock_signal.discord_thread_id == "mock_thread_98765"

    # Verify signal was saved AFTER discord notification using explicit call order verification
    mock_discord_instance.send_signal.assert_called_once_with(mock_signal)
    mock_repo_instance.save.assert_called_once_with(mock_signal)

    # Verify explicit call order: Discord notification MUST happen before Firestore save
    expected_call_order = [
        call.send_signal(mock_signal),
        call.save(mock_signal),
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
    mock_signal.pattern_name = "test_pattern"
    mock_signal.suggested_stop = 90000.0

    def side_effect(symbol, asset_class, **kwargs):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Mock notification failure
    mock_discord_instance.send_signal.return_value = False

    # Execute with caplog capturing
    import logging

    with caplog.at_level(logging.WARNING):
        main()

    # Verify warning
    assert "Failed to send Discord notification for BTC/USD" in caplog.text


def test_main_repo_failure(mock_dependencies, caplog):
    """Test that main logs an error and continues if repository save fails."""
    mock_gen_instance = mock_dependencies["generator"].return_value
    mock_repo_instance = mock_dependencies["repo"].return_value

    # Setup signals
    def gen_side_effect(symbol, asset_class, **kwargs):
        if symbol in ["BTC/USD", "ETH/USD"]:
            sig = MagicMock(spec=Signal)
            sig.symbol = symbol
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

    # Execute with caplog capturing
    import logging

    with caplog.at_level(logging.ERROR):
        main()

    # Verify error log for BTC/USD
    assert "Error processing BTC/USD (CRYPTO): Firestore Unavailable" in caplog.text

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

    import logging

    with caplog.at_level(logging.WARNING):
        main()

    # Asset: Equities should still be EMPTY because the guardrail ignored them.
    assert mock_settings.EQUITY_SYMBOLS == []

    # Verify equities were NOT processed
    calls = mock_gen_instance.generate_signals.call_args_list
    symbols = [args[0] for args, _ in calls]
    assert "AAPL" not in symbols
    assert "TSLA" not in symbols
    assert "BTC/USD" in symbols
