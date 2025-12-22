"""Unit tests for Notification Service."""

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
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
        """Test sending a real signal returns thread_id."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"id": "1234567890123456789"}
        mock_post.return_value = mock_response

        thread_id = client.send_signal(self.signal)
        self.assertEqual(thread_id, "1234567890123456789")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        # Verify ?wait=true is appended to URL
        self.assertEqual(args[0], f"{self.webhook_url}?wait=true")
        self.assertIn("🚀", kwargs["json"]["content"])
        self.assertIn("BTC/USD", kwargs["json"]["content"])

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_with_thread_name(self, mock_post):
        """Test sending a signal with a thread name."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"id": "9876543210987654321"}
        mock_post.return_value = mock_response

        thread_id = client.send_signal(self.signal, thread_name="Test Thread")
        self.assertEqual(thread_id, "9876543210987654321")

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["thread_name"], "Test Thread")

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_mocked(self, mock_post):
        """Test sending a signal in mock mode returns mock thread_id."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=True)

        thread_id = client.send_signal(self.signal)
        # Mock mode returns a deterministic thread ID based on signal_id[:8]
        self.assertEqual(thread_id, "mock_thread_test_id")

        mock_post.assert_not_called()

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_signal_failure(self, mock_post):
        """Test sending a signal when API fails returns None."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        # Simulate network error
        mock_post.side_effect = requests.RequestException("Network Error")

        thread_id = client.send_signal(self.signal)
        self.assertIsNone(thread_id)

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_message_mocked(self, mock_post):
        """Test sending a message in mock mode."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=True)

        success = client.send_message("Test Message")
        self.assertTrue(success)

        mock_post.assert_not_called()

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_message_with_thread_id_mocked(self, mock_post):
        """Test sending a reply to a thread in mock mode."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=True)

        success = client.send_message("Reply content", thread_id="1234567890")
        self.assertTrue(success)

        mock_post.assert_not_called()

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_message_with_thread_id_real(self, mock_post):
        """Test sending a reply to a thread uses ?thread_id query param."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        success = client.send_message("Reply content", thread_id="1234567890")
        self.assertTrue(success)

        mock_post.assert_called_once()
        args, _ = mock_post.call_args
        # Verify ?thread_id is appended to URL
        self.assertEqual(args[0], f"{self.webhook_url}?thread_id=1234567890")

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_message_failure(self, mock_post):
        """Test sending a message when API fails."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        # Simulate network error
        mock_post.side_effect = requests.RequestException("Network Error")

        success = client.send_message("Test Message")
        self.assertFalse(success)

    @patch("crypto_signals.notifications.discord.requests.post")
    def test_send_message_thread_reply_failure_does_not_crash(self, mock_post):
        """Test that thread reply failure logs error but doesn't crash."""
        client = DiscordClient(webhook_url=self.webhook_url, mock_mode=False)

        # Simulate network error on thread reply
        mock_post.side_effect = requests.RequestException("Thread not found")

        # Should return False but not raise exception
        success = client.send_message("Reply content", thread_id="invalid_thread")
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
        mock_response.json.return_value = {"id": "thread_123"}
        mock_post.return_value = mock_response

        thread_id = client.send_signal(full_signal)
        self.assertEqual(thread_id, "thread_123")

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
        mock_response.json.return_value = {"id": "partial_thread_123"}
        mock_post.return_value = mock_response

        thread_id = client.send_signal(partial_signal)
        self.assertEqual(thread_id, "partial_thread_123")

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        content = kwargs["json"]["content"]

        self.assertIn("XRP/USD", content)
        self.assertIn("Take Profit 1 (Conservative):** $1.60", content)
        self.assertNotIn("Take Profit 2", content)
        self.assertNotIn("Take Profit 3", content)
        self.assertNotIn("Invalidation Price", content)


# =============================================================================
# VISUAL INTEGRATION TESTS (Skip by default, run with RUN_VISUAL_TESTS=true)
# =============================================================================

# Skip visual tests unless explicitly enabled
SKIP_VISUAL = not os.environ.get("RUN_VISUAL_TESTS", "").lower() == "true"
SKIP_REASON = (
    "Visual tests require RUN_VISUAL_TESTS=true and TEST_DISCORD_WEBHOOK env vars"
)


@pytest.mark.visual
@pytest.mark.skipif(SKIP_VISUAL, reason=SKIP_REASON)
class TestVisualDiscordIntegration:
    """
    Visual integration tests that send real messages to Discord.

    These tests are skipped by default. To run them:
    1. Set TEST_DISCORD_WEBHOOK to your test webhook URL
    2. Set RUN_VISUAL_TESTS=true
    3. Run: pytest -m visual tests/test_notifications.py -v
    """

    @pytest.fixture
    def real_client(self):
        """Create a real DiscordClient for visual testing."""
        from crypto_signals.notifications.discord import DiscordClient

        webhook_url = os.environ.get("TEST_DISCORD_WEBHOOK")
        if not webhook_url:
            pytest.skip("TEST_DISCORD_WEBHOOK not set")

        return DiscordClient(webhook_url=webhook_url, mock_mode=False)

    @pytest.fixture
    def test_signal(self):
        """Create a test signal for visual verification."""
        from crypto_signals.domain.schemas import (
            AssetClass,
            Signal,
            SignalStatus,
            get_deterministic_id,
        )

        now = datetime.now(timezone.utc)
        return Signal(
            signal_id=get_deterministic_id(f"visual_test_{now.isoformat()}"),
            ds=date.today(),
            strategy_id="visual_test",
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            entry_price=95000.00,
            pattern_name="bullish_engulfing",
            status=SignalStatus.WAITING,
            suggested_stop=91000.00,
            take_profit_1=98500.00,
            take_profit_2=102000.00,
            take_profit_3=110000.00,
            expiration_at=now + timedelta(hours=24),
        )

    def test_visual_threading_success_path(self, real_client, test_signal):
        """Visual test: Verify threading works for success path."""
        import time

        # Step 1: Send initial signal (creates thread)
        thread_id = real_client.send_signal(
            test_signal, thread_name="🧪 Pytest Visual: Success"
        )
        assert thread_id is not None, "Failed to create thread"

        time.sleep(2)

        # Step 2: Send TP1 update to thread
        result = real_client.send_message(
            "🎯 **TP1 HIT** - Visual test confirmation",
            thread_id=thread_id,
        )
        assert result is True, "Failed to send TP1 update"

        # Verify visually in Discord

    def test_visual_threading_reply(self, real_client, test_signal):
        """Visual test: Verify reply appears in same thread."""
        import time

        # Create thread
        thread_id = real_client.send_signal(
            test_signal, thread_name="🧪 Pytest Visual: Reply Test"
        )
        assert thread_id is not None

        time.sleep(1)

        # Send reply
        result = real_client.send_message(
            "This message should appear as a reply in the same thread.",
            thread_id=thread_id,
        )
        assert result is True
