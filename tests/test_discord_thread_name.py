"""Test that send_signal includes thread_name in payload for Forum channels."""

from unittest.mock import MagicMock, patch


def test_send_signal_includes_thread_name_for_forum_channels():
    """
    Regression test for Discord Forum channel thread_name bug.

    Verifies that send_signal() includes thread_name in the Discord API
    payload to prevent 220001 error (Forum channels require thread_name).
    """
    from datetime import date

    from crypto_signals.domain.schemas import AssetClass, Signal, SignalStatus
    from crypto_signals.notifications.discord import DiscordClient

    # Create a mock settings object
    with patch("crypto_signals.notifications.discord.get_settings") as mock_settings:
        settings_instance = MagicMock()
        settings_instance.TEST_MODE = False
        settings_instance.LIVE_CRYPTO_DISCORD_WEBHOOK_URL = MagicMock()
        settings_instance.LIVE_CRYPTO_DISCORD_WEBHOOK_URL.get_secret_value.return_value = "https://discord.com/api/webhooks/test/webhook"
        mock_settings.return_value = settings_instance

        # Create Discord client
        client = DiscordClient(settings=settings_instance)

        # Create a test signal
        signal = Signal(
            signal_id="test-signal-123",
            ds=date(2025, 1, 15),
            strategy_id="test-strategy",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            pattern_name="inverse_head_shoulders",
            entry_price=50000.0,
            suggested_stop=48000.0,
            take_profit_1=52000.0,
            status=SignalStatus.WAITING,
        )

        # Mock the requests.post call to capture the payload
        with patch("crypto_signals.notifications.discord.requests.post") as mock_post:
            # Mock successful response
            mock_response = MagicMock()
            mock_response.json.return_value = {"id": "thread_12345"}
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            # Call send_signal
            thread_id = client.send_signal(signal)

            # Verify thread_id was returned
            assert thread_id == "thread_12345"

            # Verify requests.post was called
            assert mock_post.called

            # Extract the JSON payload from the call
            call_args = mock_post.call_args
            json_payload = call_args.kwargs.get("json")

            # CRITICAL ASSERTION: thread_name MUST be present in payload
            assert "thread_name" in json_payload, (
                "send_signal() must include 'thread_name' in payload for Forum channels. "
                "Missing thread_name causes Discord API error 220001."
            )

            # Verify thread_name format is correct
            thread_name = json_payload["thread_name"]
            assert "BTC/USD" in thread_name
            assert "Inverse Head Shoulders" in thread_name

            # Verify it contains an emoji (either rocket or building)
            assert any(emoji in thread_name for emoji in ["🚀", "🏛️", "📊"])
