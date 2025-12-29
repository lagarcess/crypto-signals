"""
Discord Notification Service.

This module handles sending formatted trade signals to Discord Webhooks.
It supports multi-webhook routing based on TEST_MODE and asset class.
"""

from typing import Optional

import requests
from crypto_signals.analysis.patterns import MACRO_PATTERN
from crypto_signals.config import Settings, get_settings
from crypto_signals.domain.schemas import AssetClass, Position, Signal
from loguru import logger

# =============================================================================
# EMOJI PALETTE - Trader's Visual Language
# =============================================================================
EMOJI_ROCKET = "🚀"  # Entry/Confirmed signal
EMOJI_DIAMOND = "💎"  # Active trade (diamond hands)
EMOJI_STOP = "🛑"  # Stop loss / Invalidated
EMOJI_MONEY = "💰"  # Profit / Win
EMOJI_SKULL = "💀"  # Loss / Rekt
EMOJI_GHOST = "👻"  # Expired signal
EMOJI_TARGET = "🎯"  # Take profit hit
EMOJI_RUNNER = "🏃"  # Trail update


class DiscordClient:
    """
    Client for interacting with Discord Webhooks.

    Supports context-aware routing based on TEST_MODE and asset class:
    - TEST_MODE=True: All traffic routes to TEST_DISCORD_WEBHOOK
    - TEST_MODE=False: Routes by asset class to LIVE_CRYPTO/LIVE_STOCK webhooks
    - System messages (no asset_class): Always route to TEST_DISCORD_WEBHOOK
    """

    def __init__(self, settings: Settings | None = None):
        """
        Initialize the DiscordClient.

        Args:
            settings: Optional Settings object for routing. Defaults to get_settings().
        """
        self.settings = settings or get_settings()

    def _get_webhook_url(self, asset_class: AssetClass | None = None) -> str | None:
        """
        Determine the correct webhook URL based on TEST_MODE and asset class.

        Routing Matrix:
        - TEST_MODE=True: Always returns TEST_DISCORD_WEBHOOK
        - TEST_MODE=False + CRYPTO: Returns LIVE_CRYPTO_DISCORD_WEBHOOK_URL
        - TEST_MODE=False + EQUITY: Returns LIVE_STOCK_DISCORD_WEBHOOK_URL
        - No asset_class (system messages): Returns TEST_DISCORD_WEBHOOK

        Args:
            asset_class: Optional asset class for routing (CRYPTO or EQUITY)

        Returns:
            Webhook URL string, or None if not configured
        """
        # TEST_MODE: All traffic goes to test webhook
        if self.settings.TEST_MODE:
            return self.settings.TEST_DISCORD_WEBHOOK.get_secret_value()

        # LIVE MODE: Route by asset class
        if asset_class == AssetClass.CRYPTO:
            webhook = self.settings.LIVE_CRYPTO_DISCORD_WEBHOOK_URL
            return webhook.get_secret_value() if webhook else None
        elif asset_class == AssetClass.EQUITY:
            webhook = self.settings.LIVE_STOCK_DISCORD_WEBHOOK_URL
            return webhook.get_secret_value() if webhook else None

        # Fallback for system messages (no asset class) - use test webhook
        return self.settings.TEST_DISCORD_WEBHOOK.get_secret_value()

    def _get_channel_id(self, asset_class: AssetClass | None = None) -> str | None:
        """
        Get the Channel ID for the given asset class (required for Bot API).
        """
        # If TEST_MODE is True, we might not have a test channel ID configured.
        # Currently config only has LIVE_CRYPTO/STOCK channel IDs.
        # We'll allow recovery if keys are present regardless of mode,
        # or STRICTLY follow LIVE/TEST separation.
        # For this implementation: specific channel IDs match specific asset classes.

        if asset_class == AssetClass.CRYPTO:
            return self.settings.DISCORD_CHANNEL_ID_CRYPTO
        elif asset_class == AssetClass.EQUITY:
            return self.settings.DISCORD_CHANNEL_ID_STOCK
        return None

    def find_thread_by_signal_id(
        self, signal_id: str, symbol: str, asset_class: AssetClass
    ) -> str | None:
        """
        Attempt to find an existing Discord thread for a signal using the Bot API.

        Searches active threads in the configured channel.
        This requires DISCORD_BOT_TOKEN and Channel IDs to be configured.

        Supports both Text channels and Forum channels by detecting channel type
        and using the appropriate API endpoint.

        Args:
            signal_id: The unique signal ID to search for.
            symbol: Ticker symbol (secondary check).
            asset_class: Asset class to determine which channel to search.

        Returns:
            str | None: The thread_id if found, else None.
        """
        token = self.settings.DISCORD_BOT_TOKEN
        if not token:
            logger.debug("Skipping thread recovery: No DISCORD_BOT_TOKEN configured.")
            return None

        channel_id = self._get_channel_id(asset_class)
        if not channel_id:
            logger.debug(f"Skipping thread recovery: No Channel ID for {asset_class}.")
            return None

        headers = {
            "Authorization": f"Bot {token.get_secret_value()}",
            "Content-Type": "application/json",
        }

        try:
            # First, get channel info to determine type
            channel_response = requests.get(
                f"https://discord.com/api/v10/channels/{channel_id}",
                headers=headers,
                timeout=5.0,
            )
            if channel_response.status_code != 200:
                logger.warning(
                    f"Cannot access channel {channel_id}: {channel_response.status_code}"
                )
                return None

            channel_info = channel_response.json()
            channel_type = channel_info.get("type", 0)
            guild_id = channel_info.get("guild_id")

            # Channel type 15 = Forum Channel (uses guild-level threads endpoint)
            # Channel type 0 = Text Channel (can use channel-level endpoint)
            if channel_type == 15 and guild_id:
                url = f"https://discord.com/api/v10/guilds/{guild_id}/threads/active"
            else:
                url = f"https://discord.com/api/v10/channels/{channel_id}/threads/active"

            response = requests.get(url, headers=headers, timeout=5.0)
            if response.status_code == 403:
                logger.warning("Discord Bot lacks permission to read threads (403).")
                return None
            if response.status_code == 404:
                logger.debug(f"No threads endpoint found for channel {channel_id}")
                return None
            response.raise_for_status()

            threads_data = response.json()
            threads = threads_data.get("threads", [])

            # For guild-level endpoint, filter to only threads in our target channel
            if channel_type == 15:
                threads = [t for t in threads if t.get("parent_id") == channel_id]

            # Search for signal_id in thread name
            search_term = f"[{signal_id}]"

            for thread in threads:
                t_name = thread.get("name", "")
                if search_term in t_name:
                    logger.info(
                        f"Recovered Discord thread {thread['id']} for {signal_id}"
                    )
                    return thread["id"]

            logger.debug(f"No active thread found for {signal_id}")
            return None

        except requests.RequestException as e:
            logger.error(f"Failed to search Discord threads: {e}")
            return None

    def send_signal(
        self, signal: Signal, thread_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Send a formatted signal alert to Discord and return the thread ID.

        Uses Discord's ?wait=true parameter to receive the full Message object,
        which includes the message ID that serves as the thread_id for Forum posts.
        This enables subsequent lifecycle updates to be pinned to the same thread.

        Automatically generates thread_name for Forum channels if not provided.

        Args:
            signal: The signal to broadcast.
            thread_name: Optional thread name override for Forum Channels.
                        If not provided, auto-generates from signal pattern/symbol.

        Returns:
            Optional[str]: The thread_id (message ID) if successful, None otherwise.
        """
        webhook_url = self._get_webhook_url(signal.asset_class)
        if not webhook_url:
            logger.critical(
                f"CRITICAL: Routing failed for {signal.asset_class}. "
                "No webhook configured for this path."
            )
            return None

        message = self._format_message(signal)

        # Auto-generate thread_name if not provided (required for Forum channels)
        if not thread_name:
            # Determine emoji (matches _format_message logic)
            BULLISH_PATTERNS = {
                "bullish_engulfing",
                "bullish_hammer",
                "bullish_harami",
                "bullish_marubozu",
                "bullish_belt_hold",
                "bullish_kicker",
                "morning_star",
                "three_white_soldiers",
                "three_inside_up",
                "piercing_line",
                "inverted_hammer",
                "dragonfly_doji",
                "double_bottom",
                "inverse_head_shoulders",
                "bull_flag",
                "cup_and_handle",
                "ascending_triangle",
                "falling_wedge",
                "rising_three_methods",
                "tweezer_bottoms",
            }
            pattern_lower = signal.pattern_name.lower()
            is_bullish = pattern_lower in BULLISH_PATTERNS or "bullish" in pattern_lower

            # MACRO patterns get building emoji
            if signal.pattern_classification == MACRO_PATTERN:
                emoji = "🏛️"
            else:
                emoji = EMOJI_ROCKET if is_bullish else "📊"

            # Format pattern name
            pattern_display = signal.pattern_name.replace("_", " ").title()

            # Generate thread name
            thread_name = f"{emoji} {signal.symbol} {pattern_display}"

        message["thread_name"] = thread_name

        # Append ?wait=true to get the full Message object with ID
        url = f"{webhook_url}?wait=true"

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

    def send_message(
        self,
        content: str,
        thread_id: Optional[str] = None,
        thread_name: Optional[str] = None,
        asset_class: AssetClass | None = None,
    ) -> bool:
        """
        Send a generic text message to Discord, optionally as a reply in a thread.

        Args:
            content: The message content.
            thread_id: Optional thread ID to reply within an existing thread.
                       If provided, the message appears as a reply in that thread.
            thread_name: Optional thread name for Forum channels. Creates a new thread
                         with this name. Ignored if thread_id is provided.
            asset_class: Optional asset class for routing. If None, routes to test webhook.

        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
        webhook_url = self._get_webhook_url(asset_class)
        if not webhook_url:
            logger.critical(
                f"CRITICAL: Routing failed for {asset_class}. "
                "No webhook configured for this path."
            )
            return False

        payload = {
            "content": content,
            "username": "Crypto Sentinel",
        }

        # For Forum channels: add thread_name to create a new thread
        if thread_name and not thread_id:
            payload["thread_name"] = thread_name

        # Build URL with optional thread_id query parameter
        url = webhook_url
        if thread_id:
            url = f"{webhook_url}?thread_id={thread_id}"

        try:
            response = requests.post(url, json=payload, timeout=5.0)
            response.raise_for_status()
            if thread_id:
                logger.info(f"Sent reply to thread {thread_id} on Discord.")
            elif thread_name:
                logger.info(f"Created new thread '{thread_name}' on Discord.")
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

    def send_trail_update(
        self,
        signal: Signal,
        old_stop: float,
        asset_class: AssetClass | None = None,
    ) -> bool:
        """
        Send a trail update notification when the Runner stop moves significantly.

        Args:
            signal: Signal with updated take_profit_3 (new trailing stop)
            old_stop: Previous trailing stop value (last notified value for UX continuity)
            asset_class: Optional asset class for routing. Defaults to signal.asset_class.

        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
        from crypto_signals.domain.schemas import OrderSide

        new_stop = signal.take_profit_3 or 0.0
        is_long = signal.side != OrderSide.SELL

        # Directional emojis: Runner + direction indicator
        emoji = f"{EMOJI_RUNNER}📈" if is_long else f"{EMOJI_RUNNER}📉"
        direction = "▲" if is_long else "▼"

        # Test mode label for differentiating test messages
        test_label = "[TEST] " if self.settings.TEST_MODE else ""

        content = (
            f"{emoji} **{test_label}TRAIL UPDATE: {signal.symbol}** {emoji}\n"
            f"New Stop: ${new_stop:,.2f} {direction}\n"
            f"Previous: ${old_stop:,.2f}"
        )

        # Use provided asset_class, or fall back to signal's asset_class
        effective_asset_class = (
            asset_class if asset_class is not None else signal.asset_class
        )

        return self.send_message(
            content,
            thread_id=signal.discord_thread_id,
            asset_class=effective_asset_class,
        )

    def send_signal_update(
        self,
        signal: Signal,
        asset_class: AssetClass | None = None,
    ) -> bool:
        """
        Send signal status update notification.

        Handles TP1_HIT, TP2_HIT, TP3_HIT, INVALIDATED, EXPIRED status updates.
        Includes action hints for position resizing when TP1_HIT.

        Args:
            signal: Signal with updated status and exit_reason
            asset_class: Optional asset class for routing

        Returns:
            bool: True if message sent successfully
        """
        from crypto_signals.domain.schemas import SignalStatus

        # Status-specific emoji mapping
        status_emoji = {
            SignalStatus.INVALIDATED: EMOJI_STOP,
            SignalStatus.TP1_HIT: EMOJI_TARGET,
            SignalStatus.TP2_HIT: EMOJI_ROCKET,
            SignalStatus.TP3_HIT: "🌕",
            SignalStatus.EXPIRED: EMOJI_GHOST,
        }.get(signal.status, "ℹ️")

        # Test mode label
        test_label = "[TEST] " if self.settings.TEST_MODE else ""

        # Build message content
        content = (
            f"{status_emoji} **{test_label}SIGNAL UPDATE: {signal.symbol}** {status_emoji}\n"
            f"**Status**: {signal.status.value}\n"
            f"**Pattern**: {signal.pattern_name.replace('_', ' ').title()}\n"
        )

        if signal.exit_reason:
            content += f"**Reason**: {signal.exit_reason}\n"

        # Action hints for position sizing (matches main.py TP automation)
        if signal.status == SignalStatus.TP1_HIT:
            content += (
                f"\n{EMOJI_DIAMOND} **Action**: Scaling Out (50%) & Stop -> **Breakeven**"
            )
        elif signal.status == SignalStatus.TP2_HIT:
            content += (
                f"\n{EMOJI_DIAMOND} **Action**: Scaling Out (50% remaining) & Stop -> TP1"
            )
        elif signal.status == SignalStatus.TP3_HIT:
            content += f"\n{EMOJI_RUNNER} **Runner Complete** - Trailing stop hit"

        # Use provided asset_class, or fall back to signal's asset_class
        effective_asset_class = (
            asset_class if asset_class is not None else signal.asset_class
        )

        return self.send_message(
            content,
            thread_id=signal.discord_thread_id,
            asset_class=effective_asset_class,
        )

    def send_trade_close(
        self,
        signal: Signal,
        position: Position,
        pnl_usd: float,
        pnl_pct: float,
        duration_str: str,
        exit_reason: str,
        asset_class: AssetClass | None = None,
    ) -> bool:
        """
        Send trade close notification with PnL summary.

        Uses explicit snapshots of data to guarantee message accuracy
        even if objects are being modified by other processes.

        Args:
            signal: The signal that triggered the trade
            position: The closed position with exit details
            pnl_usd: Profit/Loss in USD (explicit snapshot)
            pnl_pct: Profit/Loss as percentage (explicit snapshot)
            duration_str: Human-readable duration (e.g., "4h 12m")
            exit_reason: Exit reason string (e.g., "Take Profit 1", "Stop Loss")
            asset_class: Optional asset class for routing

        Returns:
            bool: True if message sent successfully
        """
        try:
            # Select emoji based on win/loss
            is_win = pnl_usd >= 0
            result_emoji = EMOJI_MONEY if is_win else EMOJI_SKULL
            pnl_sign = "+" if pnl_usd >= 0 else "-"

            # Format exit price
            exit_price_str = (
                f"${position.exit_fill_price:,.2f}" if position.exit_fill_price else "N/A"
            )

            # Test mode label for differentiating test messages in Discord
            test_label = "[TEST] " if self.settings.TEST_MODE else ""

            # Use absolute values for display with explicit sign prefix
            # Include pattern name for trade context
            content = (
                f"{result_emoji} **{test_label}TRADE CLOSED: {signal.symbol}** {result_emoji}\n"
                f"**Pattern**: {signal.pattern_name.replace('_', ' ').title()}\n"
                f"**Result**: {pnl_sign}${abs(pnl_usd):,.2f} ({pnl_sign}{abs(pnl_pct):.2f}%)\n"
                f"**Duration**: {duration_str}\n"
                f"**Exit**: {exit_reason} ({exit_price_str})\n"
                f"**Entry**: ${position.entry_fill_price:,.2f} | Qty: {position.qty}"
            )

            # Add slippage info if available
            if position.entry_slippage_pct is not None:
                slippage_emoji = "📉" if position.entry_slippage_pct > 0 else "📈"
                content += f"\n{slippage_emoji} **Entry Slippage**: {position.entry_slippage_pct:+.2f}%"

            # Add broker fees if any
            if position.commission > 0:
                content += f"\n💸 **Broker Fees**: ${position.commission:.2f}"

            # Use provided asset_class, or fall back to signal's asset_class
            effective_asset_class = (
                asset_class if asset_class is not None else signal.asset_class
            )

            return self.send_message(
                content,
                thread_id=signal.discord_thread_id,
                asset_class=effective_asset_class,
            )
        except Exception as e:
            logger.error(f"Failed to send trade close notification: {e}")
            return False

    def _format_message(self, signal: Signal) -> dict:
        """
        Format the signal into a Discord payload.

        Includes structural metadata for geometric patterns:
        - MACRO header for patterns >90 days
        - Formation Scale line
        - Pattern Geometry block with pivot anchors

        Args:
            signal: The signal object.

        Returns:
            dict: JSON payload for Discord.
        """
        # All chart patterns in this system are bullish setups
        # Use rocket emoji by default, MACRO gets building emoji
        BULLISH_PATTERNS = {
            "bullish_engulfing",
            "bullish_hammer",
            "bullish_harami",
            "bullish_marubozu",
            "bullish_belt_hold",
            "bullish_kicker",
            "morning_star",
            "three_white_soldiers",
            "three_inside_up",
            "piercing_line",
            "inverted_hammer",
            "dragonfly_doji",
            "double_bottom",
            "inverse_head_shoulders",
            "bull_flag",
            "cup_and_handle",
            "ascending_triangle",
            "falling_wedge",
            "rising_three_methods",
            "tweezer_bottoms",
        }

        pattern_lower = signal.pattern_name.lower()
        is_bullish = pattern_lower in BULLISH_PATTERNS or "bullish" in pattern_lower
        emoji = EMOJI_ROCKET if is_bullish else "📊"  # Chart emoji for neutral

        # Test mode label for differentiating test messages
        test_label = "[TEST] " if self.settings.TEST_MODE else ""

        # MACRO pattern header (structural patterns >90 days)
        macro_label = ""
        if signal.pattern_classification == MACRO_PATTERN:
            emoji = "🏛️"  # Building emoji for institutional-scale patterns
            macro_label = "[MACRO SETUP] "

        # Format the main content
        content = (
            f"{emoji} **{test_label}{macro_label}{signal.pattern_name.replace('_', ' ').upper()}** "
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

        # ============================================================
        # STRUCTURAL METADATA (Formation Scale & Pattern Geometry)
        # ============================================================
        if (
            signal.pattern_duration_days
            or signal.pattern_span_days
            or signal.structural_anchors
        ):
            content += "\n"  # Blank line separator

        # Pattern classification label (used for both span and duration)
        classification_label = (
            signal.pattern_classification.replace("_", " ").title()
            if signal.pattern_classification
            else "Standard Pattern"
        )

        # Pattern Span (actual pivot cluster timeframe)
        if signal.pattern_span_days is not None:
            content += f"\n**Pattern Span:** {signal.pattern_span_days} days"

        # Formation Age (total duration from first pivot to current bar)
        if signal.pattern_duration_days:
            content += f"\n**Formation Age:** {signal.pattern_duration_days} days ({classification_label})"

        # Pattern Geometry block
        if signal.structural_anchors:
            content += self._format_geometry_block(signal)

        # We can add more fields if needed, like timestamp or status
        payload = {
            "content": content,
            "username": "Crypto Sentinel",
            "avatar_url": (
                "https://cdn-icons-png.flaticon.com/512/6001/6001368.png"
            ),  # Generic chart icon
        }

        return payload

    def _format_geometry_block(self, signal: Signal) -> str:
        """Format structural anchors into a Pattern Geometry text block.

        Displays pivots chronologically with "Days Ago" calculation.

        Example output:
            **Pattern Geometry**
            • Valley: $42,150.25 (94 days ago)
            • Peak: $48,900.50 (42 days ago)
            • Valley: $42,300.10 (Today)

        Args:
            signal: Signal with structural_anchors populated

        Returns:
            str: Formatted geometry block for Discord message
        """
        if not signal.structural_anchors:
            return ""

        # Sort by index (chronological order)
        sorted_anchors = sorted(
            signal.structural_anchors, key=lambda a: a.get("index", 0)
        )

        # Calculate current index for "days ago" calculation
        # Use signal ds as reference point
        from datetime import datetime

        lines = ["\n**Pattern Geometry**"]

        for anchor in sorted_anchors:
            price = anchor.get("price", 0)
            pivot_type = anchor.get("pivot_type", "Point").title()
            timestamp_str = anchor.get("timestamp")

            # Calculate days ago
            days_ago_text = ""
            if timestamp_str and signal.ds:
                try:
                    # Parse timestamp (format: "2024-01-15 00:00:00" or similar)
                    pivot_date = datetime.fromisoformat(timestamp_str.split()[0]).date()
                    signal_date = signal.ds
                    days_diff = (signal_date - pivot_date).days

                    if days_diff == 0:
                        days_ago_text = "Today"
                    elif days_diff == 1:
                        days_ago_text = "1 day ago"
                    else:
                        days_ago_text = f"{days_diff} days ago"
                except (ValueError, IndexError):
                    # Fallback if timestamp parsing fails
                    days_ago_text = ""

            # Format line
            if days_ago_text:
                lines.append(f"• {pivot_type}: ${price:,.2f} ({days_ago_text})")
            else:
                lines.append(f"• {pivot_type}: ${price:,.2f}")

        return "\n".join(lines)

    # =========================================================================
    # SHADOW SIGNAL ROUTING
    # =========================================================================

    def send_shadow_signal(self, signal: Signal) -> bool:
        """Send a rejected signal to the shadow signals Discord channel.

        Shadow signals are patterns that were detected but failed quality gates
        (e.g., Volume < 1.5x, R:R < 1.5). They are routed to a dedicated channel
        for analysis and never appear in live trading channels.

        Uses ghost theme (👻) with prominent rejection reason header.

        Args:
            signal: Signal with status=REJECTED_BY_FILTER

        Returns:
            bool: True if message sent successfully
        """
        from crypto_signals.domain.schemas import SignalStatus

        # Safety: Only process rejected signals
        if signal.status != SignalStatus.REJECTED_BY_FILTER:
            logger.warning(
                f"send_shadow_signal called with non-rejected signal: {signal.signal_id}"
            )
            return False

        # Get shadow webhook URL
        webhook_url = self._get_shadow_webhook_url()
        if not webhook_url:
            logger.debug(
                f"[SHADOW] Skipping Discord notification - no webhook configured for {signal.symbol}"
            )
            return False

        message = self._format_shadow_message(signal)

        try:
            response = requests.post(webhook_url, json=message, timeout=5.0)
            response.raise_for_status()
            logger.debug(
                f"[SHADOW] Sent rejected signal to Discord: {signal.symbol} {signal.pattern_name}"
            )
            return True
        except requests.RequestException as e:
            # Fallback: If 400 Bad Request and 'thread_name' is present (Text channel conflict),
            # retry without 'thread_name'.
            if (
                getattr(e, "response", None) is not None
                and e.response.status_code == 400
                and "thread_name" in message
            ):
                logger.warning(
                    "[SHADOW] 400 Bad Request with thread_name. Retrying without thread_name (Text Channel Fallback)."
                )
                del message["thread_name"]
                try:
                    response = requests.post(webhook_url, json=message, timeout=5.0)
                    response.raise_for_status()
                    logger.info(
                        f"[SHADOW] Sent rejected signal (Fallback Mode): {signal.symbol}"
                    )
                    return True
                except requests.RequestException as retry_e:
                    logger.error(f"[SHADOW] Fallback retry failed: {str(retry_e)}")
                    return False

            if getattr(e, "response", None) is not None:
                # Log rate limiting specifically
                if e.response.status_code == 429:
                    logger.warning(
                        "[SHADOW] Discord rate limit hit - consider increasing scan interval"
                    )
                else:
                    logger.debug(f"[SHADOW] Discord Response: {e.response.text}")
            logger.debug(f"[SHADOW] Failed to send notification: {str(e)}")
            return False

    def _get_shadow_webhook_url(self) -> str | None:
        """Get the shadow signals webhook URL.

        In TEST_MODE, uses TEST_DISCORD_WEBHOOK to avoid needing separate
        shadow channel configuration during development.
        """
        # In TEST_MODE, shadow signals also go to test webhook
        if self.settings.TEST_MODE:
            return self.settings.TEST_DISCORD_WEBHOOK.get_secret_value()

        # Production mode: use dedicated shadow webhook if configured
        webhook = self.settings.DISCORD_SHADOW_WEBHOOK_URL
        return webhook.get_secret_value() if webhook else None

    def _format_shadow_message(self, signal: Signal) -> dict:
        """Format a rejected signal into a Discord embed with grey theme.

        Uses Discord embed format with:
        - Grey color (8421504) for shadow signals
        - Rejection reason in title
        - Confluence Snapshot field showing indicator values
        - Pattern Geometry for multi-day patterns / Candle Context for candlestick patterns

        Args:
            signal: Rejected signal with rejection_reason and confluence_snapshot

        Returns:
            dict: JSON payload with embeds for Discord webhook
        """
        # Format rejection reason for title
        rejection_reason = (
            (signal.rejection_reason or "Unknown").upper().replace("_", " ")
        )

        # Test mode label
        test_label = "[TEST] " if self.settings.TEST_MODE else ""
        pattern_display = signal.pattern_name.replace("_", " ").title()

        # Build embed fields
        fields = []

        # 🚫 Rejection Reason field
        fields.append(
            {
                "name": "🚫 Rejection Reason",
                "value": signal.rejection_reason or "Unknown",
                "inline": False,
            }
        )

        # 🧩 Confluence Snapshot field
        if signal.confluence_snapshot:
            snapshot = signal.confluence_snapshot
            snapshot_parts = []
            if "rsi" in snapshot:
                snapshot_parts.append(f"RSI: {snapshot['rsi']}")
            if "adx" in snapshot:
                snapshot_parts.append(f"ADX: {snapshot['adx']}")
            if "sma_trend" in snapshot:
                snapshot_parts.append(f"SMA200: {snapshot['sma_trend']}")
            if "volume_ratio" in snapshot:
                snapshot_parts.append(f"Vol: {snapshot['volume_ratio']}x")
            if "rr_ratio" in snapshot:
                snapshot_parts.append(f"R:R: {snapshot['rr_ratio']}")

            if snapshot_parts:
                fields.append(
                    {
                        "name": "🧩 Confluence Snapshot",
                        "value": " | ".join(snapshot_parts),
                        "inline": False,
                    }
                )

        # 📐 Pattern Geometry / Candle Context field
        geometry_text = self._format_geometry_or_candle_context(signal)
        if geometry_text:
            fields.append(
                {
                    "name": "📐 Pattern Geometry",
                    "value": geometry_text,
                    "inline": False,
                }
            )

        # Price levels
        price_text = (
            f"Entry: ${signal.entry_price:,.2f} | Stop: ${signal.suggested_stop:,.2f}"
        )
        if signal.take_profit_1:
            price_text += f" | TP1: ${signal.take_profit_1:,.2f}"
        fields.append(
            {
                "name": "📊 Price Levels",
                "value": price_text,
                "inline": False,
            }
        )

        # Build the embed
        embed = {
            "title": f"{EMOJI_GHOST} {test_label}[REJECTED: {rejection_reason}]",
            "description": f"**{signal.symbol}** {pattern_display}",
            "color": 8421504,  # Grey color for shadow signals
            "fields": fields,
        }

        # Footer with formation metadata (if available)
        if signal.pattern_duration_days or signal.pattern_span_days:
            classification = (
                signal.pattern_classification.replace("_", " ").title()
                if signal.pattern_classification
                else "Standard"
            )

            # Build footer text with both metrics
            footer_parts = []
            if signal.pattern_span_days is not None:
                footer_parts.append(f"Span: {signal.pattern_span_days}d")
            if signal.pattern_duration_days:
                footer_parts.append(
                    f"Age: {signal.pattern_duration_days}d ({classification})"
                )

            if footer_parts:
                embed["footer"] = {"text": " | ".join(footer_parts)}

        return {
            "embeds": [embed],
            "username": "Shadow Sentinel",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/3144/3144456.png",
            "thread_name": f"{EMOJI_GHOST} [REJECTED] {signal.symbol} {pattern_display}",
        }

    def _format_geometry_or_candle_context(self, signal: Signal) -> str:
        """Format pattern geometry for multi-day patterns or candle context for candlestick patterns.

        Args:
            signal: Signal with structural_anchors (multi-day) or candlestick pattern

        Returns:
            str: Formatted geometry/context string, or empty if not applicable
        """
        # Multi-day patterns with structural anchors
        if signal.structural_anchors:
            from datetime import datetime

            lines = []
            sorted_anchors = sorted(
                signal.structural_anchors, key=lambda a: a.get("index", 0)
            )

            for anchor in sorted_anchors[:5]:  # Limit to 5 pivots
                price = anchor.get("price", 0)
                pivot_type = anchor.get("pivot_type", "Point").title()
                timestamp_str = anchor.get("timestamp")

                days_ago_text = ""
                if timestamp_str and signal.ds:
                    try:
                        pivot_date = datetime.fromisoformat(
                            timestamp_str.split()[0]
                        ).date()
                        days_diff = (signal.ds - pivot_date).days
                        if days_diff == 0:
                            days_ago_text = "Today"
                        elif days_diff == 1:
                            days_ago_text = "1d ago"
                        else:
                            days_ago_text = f"{days_diff}d ago"
                    except (ValueError, IndexError):
                        pass

                if days_ago_text:
                    lines.append(f"• {pivot_type}: ${price:,.2f} ({days_ago_text})")
                else:
                    lines.append(f"• {pivot_type}: ${price:,.2f}")

            return "\n".join(lines) if lines else ""

        # Candlestick patterns - show basic candle context
        candlestick_patterns = (
            "BULLISH_HAMMER",
            "BULLISH_ENGULFING",
            "MORNING_STAR",
            "DRAGONFLY_DOJI",
            "BULLISH_HARAMI",
            "BULLISH_MARUBOZU",
            "INVERTED_HAMMER",
            "PIERCING_LINE",
            "THREE_WHITE_SOLDIERS",
            "BULLISH_KICKER",
            "BULLISH_BELT_HOLD",
            "THREE_INSIDE_UP",
            "RISING_THREE_METHODS",
            "TWEEZER_BOTTOMS",
        )

        if signal.pattern_name in candlestick_patterns:
            return f"Entry: ${signal.entry_price:,.2f}"

        return ""
