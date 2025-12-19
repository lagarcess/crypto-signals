"""
Discord Notification Service.

This module handles sending formatted trade signals to a Discord Webhook.
It supports a mock mode for local development and testing to prevent spamming
real channels.
"""

import logging
from typing import Optional

import requests

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import Signal

logger = logging.getLogger(__name__)


class DiscordClient:
    """Client for interacting with Discord Webhooks."""

    def __init__(
        self, webhook_url: Optional[str] = None, mock_mode: Optional[bool] = None
    ):
        """
        Initialize the DiscordClient.

        Args:
            webhook_url: Optional override for webhook URL. Defaults to config settings.
            mock_mode: Optional override for mock mode. Defaults to config settings.
        """
        settings = get_settings()
        self.webhook_url = webhook_url or settings.DISCORD_WEBHOOK_URL
        # Explicit check for None to allow passing False
        self.mock_mode = mock_mode if mock_mode is not None else settings.MOCK_DISCORD

    def send_signal(self, signal: Signal, thread_name: Optional[str] = None) -> bool:
        """
        Send a formatted signal alert to Discord.

        Args:
            signal: The signal to broadcast.
            thread_name: Optional thread name (required for Forum Channels).

        Returns:
            bool: True if the signal was sent successfully, False otherwise.
        """
        if self.mock_mode:
            logger.info(
                f"MOCK DISCORD: Would send signal for {signal.symbol}: "
                f"{signal.pattern_name}"
            )
            return True

        message = self._format_message(signal)
        if thread_name:
            message["thread_name"] = thread_name

        try:
            response = requests.post(self.webhook_url, json=message, timeout=5.0)
            response.raise_for_status()
            logger.info(f"Sent signal for {signal.symbol} to Discord.")
            return True
        except requests.RequestException as e:
            if getattr(e, "response", None) is not None:
                logger.error(f"Discord Response: {e.response.text}")
            logger.error(f"Failed to send Discord notification: {str(e)}")
            return False

    def send_message(self, content: str, thread_name: Optional[str] = None) -> bool:
        """
        Send a generic text message to Discord.

        Args:
            content: The message content.
            thread_name: Optional thread name (required for Forum Channels).

        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
        if self.mock_mode:
            logger.info(f"MOCK DISCORD: Would send message: {content}")
            return True

        payload = {
            "content": content,
            "username": "Crypto Sentinel",
        }
        if thread_name:
            payload["thread_name"] = thread_name

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=5.0)
            response.raise_for_status()
            logger.info("Sent generic message to Discord.")
            return True
        except requests.RequestException as e:
            if getattr(e, "response", None) is not None:
                logger.error(f"Discord Response: {e.response.text}")
            logger.error(f"Failed to send Discord notification: {str(e)}")
            return False

    def _format_message(self, signal: Signal) -> dict:
        """
        Format the signal into a Discord payload.

        Args:
            signal: The signal object.

        Returns:
            dict: JSON payload for Discord.
        """
        # Emoji selection based on pattern name:
        # bullish patterns get 🚀, others get 🔻
        # This could be refined further with more explicit bullish/bearish
        # metadata if needed.
        emoji = "🚀" if "bullish" in signal.pattern_name.lower() else "🔻"

        # Format the main content
        content = (
            f"{emoji} **{signal.pattern_name.replace('_', ' ').upper()}** "
            f"detected on **{signal.symbol}**\n"
            f"**Stop Loss:** ${signal.suggested_stop:,.2f}"
        )

        # We can add more fields if needed, like timestamp or status
        payload = {
            "content": content,
            "username": "Crypto Sentinel",
            "avatar_url": (
                "https://cdn-icons-png.flaticon.com/512/6001/6001368.png"
            ),  # Generic chart icon
        }

        return payload
