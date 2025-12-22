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
    """
    Client for interacting with Discord Webhooks.

    Supports threaded signal lifecycle where initial signals return a thread_id
    that can be used for subsequent lifecycle updates (TP hits, invalidations, etc.).
    """

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

    def send_signal(
        self, signal: Signal, thread_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Send a formatted signal alert to Discord and return the thread ID.

        Uses Discord's ?wait=true parameter to receive the full Message object,
        which includes the message ID that serves as the thread_id for Forum posts.
        This enables subsequent lifecycle updates to be pinned to the same thread.

        Args:
            signal: The signal to broadcast.
            thread_name: Optional thread name (required for Forum Channels).

        Returns:
            Optional[str]: The thread_id (message ID) if successful, None otherwise.
        """
        if self.mock_mode:
            # Return a mock thread ID for testing purposes
            mock_thread_id = f"mock_thread_{signal.signal_id[:8]}"
            logger.info(
                f"MOCK DISCORD: Would send signal for {signal.symbol}: "
                f"{signal.pattern_name} (thread_id: {mock_thread_id})"
            )
            return mock_thread_id

        message = self._format_message(signal)
        if thread_name:
            message["thread_name"] = thread_name

        # Append ?wait=true to get the full Message object with ID
        url = f"{self.webhook_url}?wait=true"

        try:
            response = requests.post(url, json=message, timeout=5.0)
            response.raise_for_status()

            # Parse response to extract thread_id (message ID for Forum posts)
            response_data = response.json()
            thread_id = response_data.get("id")

            logger.info(
                f"Sent signal for {signal.symbol} to Discord (thread_id: {thread_id})."
            )
            return thread_id
        except requests.RequestException as e:
            if getattr(e, "response", None) is not None:
                logger.error(f"Discord Response: {e.response.text}")
            logger.error(f"Failed to send Discord notification: {str(e)}")
            return None

    def send_message(self, content: str, thread_id: Optional[str] = None) -> bool:
        """
        Send a generic text message to Discord, optionally as a reply in a thread.

        Args:
            content: The message content.
            thread_id: Optional thread ID to reply within an existing thread.
                       If provided, the message appears as a reply in that thread.

        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
        if self.mock_mode:
            if thread_id:
                logger.info(
                    f"MOCK DISCORD: Replying to thread {thread_id} with: {content}"
                )
            else:
                logger.info(f"MOCK DISCORD: Would send message: {content}")
            return True

        payload = {
            "content": content,
            "username": "Crypto Sentinel",
        }

        # Build URL with optional thread_id query parameter
        url = self.webhook_url
        if thread_id:
            url = f"{self.webhook_url}?thread_id={thread_id}"

        try:
            response = requests.post(url, json=payload, timeout=5.0)
            response.raise_for_status()
            if thread_id:
                logger.info(f"Sent reply to thread {thread_id} on Discord.")
            else:
                logger.info("Sent generic message to Discord.")
            return True
        except requests.RequestException as e:
            if getattr(e, "response", None) is not None:
                logger.error(f"Discord Response: {e.response.text}")
            # Robust fallback: log error but don't crash if thread reply fails
            if thread_id:
                logger.error(
                    f"Failed to reply to thread {thread_id}: {str(e)}. "
                    "Message not delivered but execution continues."
                )
            else:
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
        emoji = "🚀" if "bullish" in signal.pattern_name.lower() else "🔻"

        # Format the main content
        content = (
            f"{emoji} **{signal.pattern_name.replace('_', ' ').upper()}** "
            f"detected on **{signal.symbol}**\n\n"
            f"**Entry Price:** ${signal.entry_price:,.2f}\n"
            f"**Stop Loss:** ${signal.suggested_stop:,.2f}"
        )

        # Add Invalidation Price if it exists and is different from suggested_stop
        if (
            signal.invalidation_price is not None
            and signal.invalidation_price != signal.suggested_stop
        ):
            content += f"\n**Invalidation Price:** ${signal.invalidation_price:,.2f}"

        # Add Take Profit targets
        if signal.take_profit_1:
            content += f"\n**Take Profit 1 (Conservative):** ${signal.take_profit_1:,.2f}"
        if signal.take_profit_2:
            content += f"\n**Take Profit 2 (Structural):** ${signal.take_profit_2:,.2f}"
        if signal.take_profit_3:
            content += f"\n**Take Profit 3 (Runner):** ${signal.take_profit_3:,.2f}"

        # We can add more fields if needed, like timestamp or status
        payload = {
            "content": content,
            "username": "Crypto Sentinel",
            "avatar_url": (
                "https://cdn-icons-png.flaticon.com/512/6001/6001368.png"
            ),  # Generic chart icon
        }

        return payload
