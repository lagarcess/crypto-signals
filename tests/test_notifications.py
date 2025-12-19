"""Unit tests for Notification Service."""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from crypto_signals.domain.schemas import Signal, SignalStatus
from crypto_signals.notifications.discord import DiscordClient


class TestDiscordClient(unittest.TestCase):
    """Test suite for DiscordClient."""

    def setUp(self):
        """Set up test fixtures."""
        self.webhook_url = "https://discord.com/api/webhooks/test"
        self.signal = Signal(
            signal_id="test_id",
            ds=date(2025, 1, 1),
            strategy_id="test_strat",
            symbol="BTC/USD",
            pattern_name="bullish_engulfing",
            status=SignalStatus.WAITING,
            suggested_stop=50000.0,
        )

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_real(self, mock_post):
        """Test sending a real signal (not mocked)."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        client.send_signal(self.signal)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], self.webhook_url)
        self.assertIn("🚀", kwargs["json"]["content"])
        self.assertIn("BTC/USD", kwargs["json"]["content"])

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_mocked(self, mock_post):
        """Test sending a signal in mock mode (should NOT hit API)."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=True)

        client.send_signal(self.signal)

        mock_post.assert_not_called()

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_message_mocked(self, mock_post):
        """Test sending a message in mock mode."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=True)

        client.send_message("Test Message")

        mock_post.assert_not_called()
