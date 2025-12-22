"""Unit tests for Notification Service."""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import requests
from crypto_signals.domain.schemas import AssetClass, Signal, SignalStatus
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
            asset_class=AssetClass.CRYPTO,
            confluence_factors=["trend_alignment", "volume_spike"],
            entry_price=48000.0,
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

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_with_targets(self, mock_post):
        """Test sending a signal with all targets and invalidation price."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        full_signal = Signal(
            signal_id="test_id_full",
            ds=date(2025, 1, 1),
            strategy_id="test_strat",
            symbol="ETH/USD",
            asset_class=AssetClass.CRYPTO,
            confluence_factors=["rsi_divergence"],
            entry_price=3050.0,
            pattern_name="BULLISH_ENGULFING",
            status=SignalStatus.WAITING,
            suggested_stop=3000.0,
            invalidation_price=2950.0,
            take_profit_1=3100.0,
            take_profit_2=3200.0,
            take_profit_3=3500.0,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        success = client.send_signal(full_signal)
        self.assertTrue(success)

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        content = kwargs["json"]["content"]

        self.assertIn("ETH/USD", content)
        self.assertIn("Entry Price:** $3,050.00", content)
        self.assertIn("Stop Loss:** $3,000.00", content)
        self.assertIn("Invalidation Price:** $2,950.00", content)
        self.assertIn("Take Profit 1 (Conservative):** $3,100.00", content)
        self.assertIn("Take Profit 2 (Structural):** $3,200.00", content)
        self.assertIn("Take Profit 3 (Runner):** $3,500.00", content)

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_partial_targets(self, mock_post):
        """Test sending a signal with missing targets (conditional rendering)."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        # Signal with only TP1 defined, TP2 and TP3 are None
        partial_signal = Signal(
            signal_id="test_id_partial",
            ds=date(2025, 1, 1),
            strategy_id="test_strat",
            symbol="XRP/USD",
            asset_class=AssetClass.CRYPTO,
            confluence_factors=["breakout"],
            entry_price=1.50,
            pattern_name="BULLISH_FLAG",
            status=SignalStatus.WAITING,
            suggested_stop=1.40,
            invalidation_price=1.40,  # Same as stop, should not show invalidation line
            take_profit_1=1.60,
            take_profit_2=None,
            take_profit_3=None,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        success = client.send_signal(partial_signal)
        self.assertTrue(success)

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        content = kwargs["json"]["content"]

        self.assertIn("XRP/USD", content)
        self.assertIn("Take Profit 1 (Conservative):** $1.60", content)
        self.assertNotIn("Take Profit 2", content)
        self.assertNotIn("Take Profit 3", content)
        self.assertNotIn("Invalidation Price", content)
