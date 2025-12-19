"""Unit tests for the main application entrypoint."""

from unittest.mock import MagicMock, call, patch

import pytest

from crypto_signals.domain.schemas import AssetClass, Signal
from crypto_signals.main import main


@pytest.fixture
def mock_dependencies():
    """Mock all external dependencies used in main.py."""
    with patch("crypto_signals.main.get_stock_data_client") as stock_client, patch(
        "crypto_signals.main.get_crypto_data_client"
    ) as crypto_client, patch(
        "crypto_signals.main.MarketDataProvider"
    ) as market_provider, patch(
        "crypto_signals.main.SignalGenerator"
    ) as generator, patch(
        "crypto_signals.main.SignalRepository"
    ) as repo, patch(
        "crypto_signals.main.DiscordClient"
    ) as discord, patch(
        "crypto_signals.main.get_settings"
    ) as mock_settings:

        # Configure mock settings
        mock_settings.return_value.CRYPTO_SYMBOLS = [
            "BTC/USD",
            "ETH/USD",
            "XRP/USD",
        ]
        mock_settings.return_value.EQUITY_SYMBOLS = [
            "NVDA",
            "QQQ",
            "GLD",
        ]

        yield {
            "stock_client": stock_client,
            "crypto_client": crypto_client,
            "market_provider": market_provider,
            "generator": generator,
            "repo": repo,
            "discord": discord,
            "settings": mock_settings,
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

    def side_effect(symbol, asset_class):
        if symbol == "BTC/USD":
            return mock_signal
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

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
        call("BTC/USD", AssetClass.CRYPTO),
        call("ETH/USD", AssetClass.CRYPTO),
        call("XRP/USD", AssetClass.CRYPTO),
        call("NVDA", AssetClass.EQUITY),
        call("QQQ", AssetClass.EQUITY),
        call("GLD", AssetClass.EQUITY),
    ]
    mock_gen_instance.generate_signals.assert_has_calls(expected_calls, any_order=False)

    # Verify Signal Handling (Save & Notify)
    # Should be called once for BTC/USD
    mock_repo_instance.save.assert_called_once_with(mock_signal)
    mock_discord_instance.send_signal.assert_called_once_with(mock_signal)


def test_main_symbol_error_handling(mock_dependencies):
    """Test that main continues processing remaining symbols if one fails."""
    mock_gen_instance = mock_dependencies["generator"].return_value

    # Make ETH/USD raise an exception
    def side_effect(symbol, asset_class):
        if symbol == "ETH/USD":
            raise ValueError("Simulated Analysis Error")
        return None

    mock_gen_instance.generate_signals.side_effect = side_effect

    # Execute (should not raise exception)
    main()

    # Verify that subsequent symbols (e.g., NVDA) were still processed
    # We check if generate_signals was called for NVDA
    calls = mock_gen_instance.generate_signals.call_args_list
    symbols_processed = [args[0] for args, _ in calls]

    assert "BTC/USD" in symbols_processed
    assert "ETH/USD" in symbols_processed
    assert "NVDA" in symbols_processed
    assert "GLD" in symbols_processed


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

    def side_effect(symbol, asset_class):
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
    def gen_side_effect(symbol, asset_class):
        if symbol in ["BTC/USD", "ETH/USD"]:
            sig = MagicMock(spec=Signal)
            sig.symbol = symbol
            sig.pattern_name = "test_pattern"
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
    assert "Error processing BTC/USD: Firestore Unavailable" in caplog.text

    # Verify that ETH/USD was still processed (Loop continued)
    # We check if generate_signals was called for ETH/USD
    calls = mock_gen_instance.generate_signals.call_args_list
    symbols_processed = [args[0] for args, _ in calls]
    assert "ETH/USD" in symbols_processed
