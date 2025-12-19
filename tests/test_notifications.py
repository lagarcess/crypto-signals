"""Unit tests for Notification Service."""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import requests

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
            pattern_name="BULLISH_ENGULFING",
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

        success = client.send_signal(self.signal)
        self.assertTrue(success)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], self.webhook_url)
        self.assertIn("🚀", kwargs["json"]["content"])
        self.assertIn("BTC/USD", kwargs["json"]["content"])

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_with_thread_name(self, mock_post):
        """Test sending a signal with a thread name."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        success = client.send_signal(self.signal, thread_name="Test Thread")
        self.assertTrue(success)

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["thread_name"], "Test Thread")

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_mocked(self, mock_post):
        """Test sending a signal in mock mode (should NOT hit API)."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=True)

        success = client.send_signal(self.signal)
        self.assertTrue(success)

        mock_post.assert_not_called()

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_failure(self, mock_post):
        """Test sending a signal when API fails."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        # Simulate network error
        mock_post.side_effect = requests.RequestException("Network Error")

        success = client.send_signal(self.signal)
        self.assertFalse(success)

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_message_mocked(self, mock_post):
        """Test sending a message in mock mode."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=True)

        success = client.send_message("Test Message")
        self.assertTrue(success)

        mock_post.assert_not_called()

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_message_failure(self, mock_post):
        """Test sending a message when API fails."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        # Simulate network error
        mock_post.side_effect = requests.RequestException("Network Error")

        success = client.send_message("Test Message")
        self.assertFalse(success)
