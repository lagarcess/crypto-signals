#!/usr/bin/env python
"""
Visual Discord Integration Test Script.

This script sends real payloads to a Discord webhook to visually verify
message threading and formatting across all signal lifecycle paths.

Usage:
    1. Set the TEST_DISCORD_WEBHOOK environment variable to your test webhook URL
    2. Run: python scripts/visual_discord_test.py [path]

    Where [path] is one of:
    - success     : Signal → TP1 → TP2 → TP3 (full success path)
    - invalidation: Signal → Invalidation
    - expiration  : Signal → Expiration
    - all         : Run all three paths (default)

Example:
    export TEST_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
    python scripts/visual_discord_test.py success
"""

import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

# Setup: Load .env and add src to path BEFORE importing project modules
load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Project imports (after path setup)  # noqa: E402
from crypto_signals.domain.schemas import (  # noqa: E402
    AssetClass,
    Signal,
    SignalStatus,
    get_deterministic_id,
)
from crypto_signals.notifications.discord import DiscordClient  # noqa: E402

# Configuration
UPDATE_DELAY_SECONDS = 2.5  # Delay between updates for visual verification


def get_webhook_url() -> str:
    """Get the test webhook URL from environment variable."""
    webhook_url = os.environ.get("TEST_DISCORD_WEBHOOK")

    if not webhook_url:
        print("\n" + "=" * 70)
        print("ERROR: TEST_DISCORD_WEBHOOK environment variable not set!")
        print("=" * 70)
        print("\nTo run this visual test, you need to:")
        print("  1. Create a test Discord channel")
        print("  2. Create a webhook for that channel")
        print("  3. Set the environment variable:")
        print()
        print("     Windows (PowerShell):")
        print('       $env:TEST_DISCORD_WEBHOOK = "https://discord.com/api/webhooks/..."')
        print()
        print("     Linux/macOS:")
        print('       export TEST_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."')
        print()
        print("  4. Run this script again")
        print("=" * 70 + "\n")
        sys.exit(1)

    return webhook_url


def create_test_signal(scenario: str) -> Signal:
    """Create a realistic test signal for visual verification."""
    now = datetime.now(timezone.utc)
    signal_key = f"{date.today()}|visual_test|BTC/USD|{scenario}"

    return Signal(
        signal_id=get_deterministic_id(signal_key),
        ds=date.today(),
        strategy_id="visual_test",
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        confluence_factors=["RSI_Divergence", "VCP_Compression", "Volume_Breakout"],
        entry_price=95000.00,
        pattern_name="bullish_engulfing",
        status=SignalStatus.WAITING,
        suggested_stop=91000.00,
        invalidation_price=92500.00,
        take_profit_1=98500.00,  # Conservative: +3.7%
        take_profit_2=102000.00,  # Structural: +7.4%
        take_profit_3=110000.00,  # Runner: +15.8%
        expiration_at=now + timedelta(hours=24),
    )


def test_success_path(client: DiscordClient) -> None:
    """
    Test the full success path: Signal → TP1 → TP2 → TP3.

    This simulates a trade that hits all three take-profit targets.
    """
    print("\n🚀 Starting SUCCESS PATH test...")
    print("-" * 50)

    signal = create_test_signal("success")

    # Step 1: Initial Signal Alert (creates thread)
    print("📤 Sending initial signal alert...")
    thread_id = client.send_signal(signal, thread_name="🧪 Visual Test: Success Path")

    if not thread_id:
        print("❌ FAILED: Could not create thread (send_signal returned None)")
        return

    print(f"✅ Thread created: {thread_id}")
    time.sleep(UPDATE_DELAY_SECONDS)

    # Step 2: TP1 Hit
    print("📤 Sending TP1 Hit update...")
    msg_tp1 = (
        "🎯 **SIGNAL UPDATE: BTC/USD** 🎯\n"
        "**Status**: TP1_HIT\n"
        "**Pattern**: BULLISH ENGULFING\n"
        "**Reason**: TP1\n"
        "**Price Hit**: $98,500.00 (+3.7%)\n"
        "ℹ️ **Action**: Scaling Out (50%) & Stop -> **Breakeven**"
    )
    client.send_message(msg_tp1, thread_id=thread_id)
    print("✅ TP1 update sent")
    time.sleep(UPDATE_DELAY_SECONDS)

    # Step 3: TP2 Hit
    print("📤 Sending TP2 Hit update...")
    msg_tp2 = (
        "🚀 **SIGNAL UPDATE: BTC/USD** 🚀\n"
        "**Status**: TP2_HIT\n"
        "**Pattern**: BULLISH ENGULFING\n"
        "**Reason**: TP2\n"
        "**Price Hit**: $102,000.00 (+7.4%)\n"
        "ℹ️ **Action**: Scaling Out (25%) & Trailing Stop Active"
    )
    client.send_message(msg_tp2, thread_id=thread_id)
    print("✅ TP2 update sent")
    time.sleep(UPDATE_DELAY_SECONDS)

    # Step 4: TP3 Hit (Runner Exit)
    print("📤 Sending TP3 Hit (Runner Exit) update...")
    msg_tp3 = (
        "🌕 **SIGNAL UPDATE: BTC/USD** 🌕\n"
        "**Status**: TP3_HIT\n"
        "**Pattern**: BULLISH ENGULFING\n"
        "**Reason**: TP3 (Runner Target)\n"
        "**Price Hit**: $110,000.00 (+15.8%)\n"
        "🎉 **TRADE COMPLETE** - Full target achieved!"
    )
    client.send_message(msg_tp3, thread_id=thread_id)
    print("✅ TP3 (Runner Exit) update sent")

    print("-" * 50)
    print("✅ SUCCESS PATH test complete!")
    print(f"   Thread ID: {thread_id}")
    print("   Please verify in Discord that all 4 messages appear in the same thread.\n")


def test_invalidation_path(client: DiscordClient) -> None:
    """
    Test the invalidation path: Signal → Invalidation.

    This simulates a trade that gets invalidated due to structural breakdown.
    """
    print("\n🚫 Starting INVALIDATION PATH test...")
    print("-" * 50)

    signal = create_test_signal("invalidation")

    # Step 1: Initial Signal Alert (creates thread)
    print("📤 Sending initial signal alert...")
    thread_id = client.send_signal(
        signal, thread_name="🧪 Visual Test: Invalidation Path"
    )

    if not thread_id:
        print("❌ FAILED: Could not create thread (send_signal returned None)")
        return

    print(f"✅ Thread created: {thread_id}")
    time.sleep(UPDATE_DELAY_SECONDS)

    # Step 2: Invalidation
    print("📤 Sending invalidation update...")
    msg_invalidation = (
        "🚫 **SIGNAL UPDATE: BTC/USD** 🚫\n"
        "**Status**: INVALIDATED\n"
        "**Pattern**: BULLISH ENGULFING\n"
        "**Reason**: STRUCTURAL_INVALIDATION\n"
        "**Invalidation Price**: $92,500.00\n"
        "⚠️ **Action**: Exit position immediately - Structure has broken down"
    )
    client.send_message(msg_invalidation, thread_id=thread_id)
    print("✅ Invalidation update sent")

    print("-" * 50)
    print("✅ INVALIDATION PATH test complete!")
    print(f"   Thread ID: {thread_id}")
    print("   Please verify in Discord that both messages appear in the same thread.\n")


def test_expiration_path(client: DiscordClient) -> None:
    """
    Test the expiration path: Signal → Expiration.

    This simulates a trade that expires after 24 hours without entry.
    """
    print("\n⏳ Starting EXPIRATION PATH test...")
    print("-" * 50)

    signal = create_test_signal("expiration")

    # Step 1: Initial Signal Alert (creates thread)
    print("📤 Sending initial signal alert...")
    thread_id = client.send_signal(signal, thread_name="🧪 Visual Test: Expiration Path")

    if not thread_id:
        print("❌ FAILED: Could not create thread (send_signal returned None)")
        return

    print(f"✅ Thread created: {thread_id}")
    time.sleep(UPDATE_DELAY_SECONDS)

    # Step 2: Expiration
    print("📤 Sending expiration update...")
    msg_expiration = (
        f"⏳ **SIGNAL EXPIRED: BTC/USD** ⏳\n"
        f"Signal from {date.today()} expired (24h Limit).\n"
        "**Pattern**: BULLISH ENGULFING\n"
        "**Original Entry**: $95,000.00\n"
        "ℹ️ No action required - signal window has closed."
    )
    client.send_message(msg_expiration, thread_id=thread_id)
    print("✅ Expiration update sent")

    print("-" * 50)
    print("✅ EXPIRATION PATH test complete!")
    print(f"   Thread ID: {thread_id}")
    print("   Please verify in Discord that both messages appear in the same thread.\n")


def run_all_tests(client: DiscordClient) -> None:
    """Run all three test paths."""
    test_success_path(client)
    print("\n" + "=" * 70 + "\n")
    time.sleep(1)

    test_invalidation_path(client)
    print("\n" + "=" * 70 + "\n")
    time.sleep(1)

    test_expiration_path(client)


def main():
    """Main entry point for visual Discord tests."""
    print("\n" + "=" * 70)
    print("  VISUAL DISCORD INTEGRATION TEST")
    print("  Testing Threaded Signal Lifecycle Messages")
    print("=" * 70)

    # Get webhook URL
    webhook_url = get_webhook_url()

    # Initialize client with real mode (no mocking)
    client = DiscordClient(webhook_url=webhook_url, mock_mode=False)

    # Mask webhook URL for security - only show source confirmation
    masked_url = f"...{webhook_url[-12:]}" if len(webhook_url) > 12 else "***"
    print(f"\n📡 Webhook configured: {masked_url} (from .env or environment)")
    print(f"⏱️  Update delay: {UPDATE_DELAY_SECONDS}s between messages\n")

    # Determine which test(s) to run
    test_path = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    if test_path == "success":
        test_success_path(client)
    elif test_path == "invalidation":
        test_invalidation_path(client)
    elif test_path == "expiration":
        test_expiration_path(client)
    elif test_path == "all":
        run_all_tests(client)
    else:
        print(f"❌ Unknown test path: {test_path}")
        print("   Valid options: success, invalidation, expiration, all")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("  VISUAL VERIFICATION COMPLETE")
    print("  Please check your Discord channel to verify threading and formatting.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
