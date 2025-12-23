#!/usr/bin/env python
"""
Visual Discord Integration Test Script.

This script sends real payloads to a Discord webhook to visually verify
message threading and formatting across all signal lifecycle paths.

Usage:
    poetry run python scripts/visual_discord_test.py [PATH] [--mode test|live]

    Where [PATH] is one of:
    - success     : Signal → TP1 → TP2 → TP3 (full success path)
    - invalidation: Signal → Invalidation
    - expiration  : Signal → Expiration
    - trail       : Signal → TP1 → Trail Updates → TP3 (runner trail path)
    - short       : Short position trail path
    - all         : Run all five paths (default)

    Modes:
    - test : Routes all traffic to TEST_DISCORD_WEBHOOK (default, safe)
    - live : Routes signals by asset class (CRYPTO → crypto webhook, EQUITY → stock webhook)

Examples:
    # Test mode (default) - all messages go to test webhook
    poetry run python scripts/visual_discord_test.py success

    # Live mode - routes to appropriate asset-class webhooks
    poetry run python scripts/visual_discord_test.py all --mode live
"""

import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Annotated

import typer
from dotenv import load_dotenv

# Setup: Load .env and add src to path BEFORE importing project modules
load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Project imports (after path setup)  # noqa: E402
from crypto_signals.config import get_settings  # noqa: E402
from crypto_signals.domain.schemas import (  # noqa: E402
    AssetClass,
    OrderSide,
    Signal,
    SignalStatus,
    get_deterministic_id,
)
from crypto_signals.notifications.discord import DiscordClient  # noqa: E402

# Configuration
UPDATE_DELAY_SECONDS = 2.5  # Delay between updates for visual verification

# Typer app
app = typer.Typer(help="Visual Discord Integration Test Script")


class TestPath(str, Enum):
    """Available test paths."""

    success = "success"
    invalidation = "invalidation"
    expiration = "expiration"
    trail = "trail"
    short = "short"
    all = "all"


class Mode(str, Enum):
    """Environment mode for webhook routing."""

    test = "test"
    live = "live"


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


def test_runner_trail_path(client: DiscordClient) -> None:
    """
    Test the runner trail path: Signal → TP1 → Trail Updates → TP3.

    This simulates a trade where the trailing stop (Chandelier Exit) moves
    multiple times during the Runner phase, testing:
    - Thread integrity: All updates stay in the same thread
    - Formatting: "New vs. Previous" price context is readable
    - Threshold respect: <1% moves are logged but not sent to Discord
    """
    print("\n🌕 Starting RUNNER TRAIL PATH test...")
    print("-" * 50)

    signal = create_test_signal("trail")
    # Entry: $95,000 | TP1: $98,500 | TP2: $102,000
    # Initial trailing stop should be above entry once in Runner phase
    # Scenario: Price rallied to ~$100K, Chandelier Exit calculates to $96,000
    signal.take_profit_3 = 96000.00

    # Step 1: Initial Signal Alert (creates thread)
    print("📤 Step 1: Sending initial signal alert...")
    thread_id = client.send_signal(
        signal, thread_name="🧪 Visual Test: Runner Trail Path"
    )

    if not thread_id:
        print("❌ FAILED: Could not create thread (send_signal returned None)")
        return

    print(f"✅ Thread created: {thread_id}")
    signal.discord_thread_id = thread_id  # Attach for subsequent updates
    # Track last NOTIFIED value for UX continuity (Option B)
    last_notified_stop = signal.take_profit_3
    time.sleep(3)  # Longer delay for visual verification

    # Step 2: TP1 Hit - Start of Runner phase
    print("📤 Step 2: Sending TP1 Hit (Runner phase begins)...")
    signal.status = SignalStatus.TP1_HIT
    msg_tp1 = (
        "🎯 **SIGNAL UPDATE: BTC/USD** 🎯\n"
        "**Status**: TP1_HIT\n"
        "**Pattern**: BULLISH ENGULFING\n"
        "**Reason**: TP1\n"
        "**Price Hit**: $98,500.00 (+3.7%)\n"
        "ℹ️ **Action**: Scaling Out (50%) & Stop → **Breakeven** ($95,000)\n"
        f"🏃📈 **Runner Phase Active** - Trailing stop now at ${signal.take_profit_3:,.2f}"
    )
    client.send_message(msg_tp1, thread_id=thread_id)
    print("✅ TP1 update sent - Runner phase started")
    time.sleep(3)

    # Step 3: Significant Move (>1%) - $96,000 → $99,000 (+3.1%)
    # Price continued to rally, Chandelier Exit moved up
    print("📤 Step 3: Sending SIGNIFICANT trail update ($96,000 → $99,000)...")
    signal.take_profit_3 = 99000.00
    movement_pct = (
        abs((signal.take_profit_3 - last_notified_stop) / last_notified_stop) * 100
    )
    print(f"   Movement: {movement_pct:.1f}% (>1% threshold → sends notification)")
    client.send_trail_update(signal, old_stop=last_notified_stop)
    last_notified_stop = signal.take_profit_3  # Update last notified
    print("✅ Significant trail update sent")
    time.sleep(3)

    # Step 4: Minor Move (<1%) - $99,000 → $99,500 (+0.5%)
    print("📤 Step 4: Simulating MINOR trail update ($99,000 → $99,500)...")
    signal.take_profit_3 = 99500.00
    movement_pct = (
        abs((signal.take_profit_3 - last_notified_stop) / last_notified_stop) * 100
    )
    print(
        f"   Movement: {movement_pct:.2f}% (<1% threshold → skipping Discord notification)"
    )
    print(f"   ℹ️  Local state updated: take_profit_3 = ${signal.take_profit_3:,.2f}")
    print(f"   ℹ️  Last notified value stays at: ${last_notified_stop:,.2f}")
    print("   ⏭️  No Discord message sent (threshold not met)")
    time.sleep(3)

    # Step 5: Another Significant Move (>1%) - $99,000 → $103,000 (+4.0%)
    # Note: Using last_notified_stop ($99,000) for display, not actual previous ($99,500)
    print("📤 Step 5: Sending SIGNIFICANT trail update ($99,000 → $103,000)...")
    signal.take_profit_3 = 103000.00
    movement_pct = (
        abs((signal.take_profit_3 - last_notified_stop) / last_notified_stop) * 100
    )
    print(
        f"   Movement from last notified: {movement_pct:.1f}% (>1% → sends notification)"
    )
    client.send_trail_update(signal, old_stop=last_notified_stop)
    last_notified_stop = signal.take_profit_3  # Update last notified
    print("✅ Significant trail update sent")
    time.sleep(3)

    # Step 6: Final TP3 Exit (Chandelier Exit triggered)
    # Price pulled back and closed below the trailing stop
    print("📤 Step 6: Sending TP3 Hit (Runner Exit)...")
    signal.status = SignalStatus.TP3_HIT
    msg_tp3 = (
        "🏃📈 **SIGNAL UPDATE: BTC/USD** 🏃📈\n"
        "**Status**: TP3_HIT\n"
        "**Pattern**: BULLISH ENGULFING\n"
        "**Reason**: TP_HIT (Chandelier Exit)\n"
        f"**Exit Price**: ~${signal.take_profit_3:,.2f} (+8.4% from entry)\n"
        "🎉 **RUNNER COMPLETE** - Profit locked via dynamic trailing!"
    )
    client.send_message(msg_tp3, thread_id=thread_id)
    print("✅ TP3 (Runner Exit) update sent")

    print("-" * 50)
    print("✅ RUNNER TRAIL PATH test complete!")
    print(f"   Thread ID: {thread_id}")
    print("   Expected messages in thread: 5 (Initial + TP1 + 2 Trail + TP3)")
    print(
        "   Note: Step 4 was skipped but Discord shows continuous values ($96K→$99K→$103K)"
    )
    print("   Please verify in Discord that all messages appear in the same thread.\n")


def test_short_runner_trail_path(client: DiscordClient) -> None:
    """
    Test the SHORT runner trail path: Signal → TP1 → Trail Updates → TP3.

    This simulates a SHORT position where the trailing stop (Chandelier Exit)
    moves DOWNWARD as price falls, testing:
    - Thread integrity: All updates stay in the same thread
    - Directional trailing: Stop moves DOWN (not up) for shorts
    - Threshold respect: <1% moves are logged but not sent to Discord
    """
    print("\n🔻 Starting SHORT RUNNER TRAIL PATH test...")
    print("-" * 50)

    signal = create_test_signal("short_trail")
    # Override for Short position scenario
    signal.side = OrderSide.SELL
    signal.entry_price = 65000.00
    signal.take_profit_1 = 62000.00  # TP1 for short is BELOW entry
    signal.take_profit_2 = 59000.00
    signal.take_profit_3 = 64000.00  # Initial trailing stop (above current price)
    signal.suggested_stop = 67000.00  # Stop loss for short is ABOVE entry
    signal.invalidation_price = 66500.00

    # Step 1: Initial Signal Alert (creates thread)
    print("📤 Step 1: Sending initial SHORT signal alert...")
    thread_id = client.send_signal(
        signal, thread_name="🧪 Visual Test: Short Runner Trail Path"
    )

    if not thread_id:
        print("❌ FAILED: Could not create thread (send_signal returned None)")
        return

    print(f"✅ Thread created: {thread_id}")
    signal.discord_thread_id = thread_id
    # Track last NOTIFIED value for UX continuity (Option B)
    last_notified_stop = signal.take_profit_3
    time.sleep(3)

    # Step 2: TP1 Hit - Start of Runner phase
    print("📤 Step 2: Sending TP1 Hit (Runner phase begins)...")
    signal.status = SignalStatus.TP1_HIT
    msg_tp1 = (
        "🎯 **SIGNAL UPDATE: BTC/USD** 🎯\n"
        "**Side**: SHORT 🔻\n"
        "**Status**: TP1_HIT\n"
        "**Pattern**: BULLISH ENGULFING (Reversal Play)\n"
        "**Price Hit**: $62,000.00 (-4.6%)\n"
        "ℹ️ **Action**: Scaling Out (50%) & Stop → **Breakeven** ($65,000)\n"
        f"🏃📉 **Runner Phase Active** - Trailing stop now at ${signal.take_profit_3:,.2f}"
    )
    client.send_message(msg_tp1, thread_id=thread_id)
    print("✅ TP1 update sent - Runner phase started")
    time.sleep(3)

    # Step 3: Significant Move (>1%) - $64,000 → $62,000 (-3.1%)
    # For shorts, trailing stop moves DOWN as price falls
    print("📤 Step 3: Sending SIGNIFICANT trail update ($64,000 → $62,000)...")
    signal.take_profit_3 = 62000.00
    movement_pct = (
        abs((signal.take_profit_3 - last_notified_stop) / last_notified_stop) * 100
    )
    print(f"   Movement: {movement_pct:.1f}% (>1% threshold → sends notification)")
    client.send_trail_update(signal, old_stop=last_notified_stop)
    last_notified_stop = signal.take_profit_3  # Update last notified
    print("✅ Significant trail update sent")
    time.sleep(3)

    # Step 4: Minor Move (<1%) - $62,000 → $61,800 (-0.3%)
    print("📤 Step 4: Simulating MINOR trail update ($62,000 → $61,800)...")
    signal.take_profit_3 = 61800.00
    movement_pct = (
        abs((signal.take_profit_3 - last_notified_stop) / last_notified_stop) * 100
    )
    print(
        f"   Movement: {movement_pct:.2f}% (<1% threshold → skipping Discord notification)"
    )
    print(f"   ℹ️  Local state updated: take_profit_3 = ${signal.take_profit_3:,.2f}")
    print(f"   ℹ️  Last notified value stays at: ${last_notified_stop:,.2f}")
    print("   ⏭️  No Discord message sent (threshold not met)")
    time.sleep(3)

    # Step 5: Another Significant Move (>1%) - $62,000 → $60,000 (-3.2%)
    # Note: Using last_notified_stop ($62,000) for display, not actual previous ($61,800)
    print("📤 Step 5: Sending SIGNIFICANT trail update ($62,000 → $60,000)...")
    signal.take_profit_3 = 60000.00
    movement_pct = (
        abs((signal.take_profit_3 - last_notified_stop) / last_notified_stop) * 100
    )
    print(
        f"   Movement from last notified: {movement_pct:.1f}% (>1% → sends notification)"
    )
    client.send_trail_update(signal, old_stop=last_notified_stop)
    last_notified_stop = signal.take_profit_3  # Update last notified
    print("✅ Significant trail update sent")
    time.sleep(3)

    # Step 6: Final TP3 Exit (price bounced above trailing stop)
    print("📤 Step 6: Sending TP3 Hit (Runner Exit)...")
    signal.status = SignalStatus.TP3_HIT
    msg_tp3 = (
        "🏃📉 **SIGNAL UPDATE: BTC/USD** 🏃📉\n"
        "**Side**: SHORT\n"
        "**Status**: TP3_HIT\n"
        "**Reason**: TP_HIT (Chandelier Exit)\n"
        f"**Exit Price**: ~${signal.take_profit_3:,.2f} (-7.7% from entry)\n"
        "🎉 **SHORT RUNNER COMPLETE** - Profit locked via downward trailing!"
    )
    client.send_message(msg_tp3, thread_id=thread_id)
    print("✅ TP3 (Runner Exit) update sent")

    print("-" * 50)
    print("✅ SHORT RUNNER TRAIL PATH test complete!")
    print(f"   Thread ID: {thread_id}")
    print("   Expected messages in thread: 5 (Initial + TP1 + 2 Trail + TP3)")
    print(
        "   Note: Step 4 was skipped but Discord shows continuous values ($64K→$62K→$60K)"
    )
    print("   Trailing stop moved DOWN as price fell.\n")


def run_all_tests(client: DiscordClient) -> None:
    """Run all four test paths."""
    test_success_path(client)
    print("\n" + "=" * 70 + "\n")
    time.sleep(1)

    test_invalidation_path(client)
    print("\n" + "=" * 70 + "\n")
    time.sleep(1)

    test_expiration_path(client)
    print("\n" + "=" * 70 + "\n")
    time.sleep(1)

    test_runner_trail_path(client)
    print("\n" + "=" * 70 + "\n")
    time.sleep(1)

    test_short_runner_trail_path(client)


@app.command()
def main(
    path: Annotated[
        TestPath,
        typer.Argument(help="Test path to run"),
    ] = TestPath.all,
    mode: Annotated[
        Mode,
        typer.Option(
            "--mode",
            "-m",
            help="Routing mode: 'test' routes all to TEST_DISCORD_WEBHOOK, 'live' routes by asset class",
        ),
    ] = Mode.test,
) -> None:
    """Run visual Discord integration tests."""
    print("\n" + "=" * 70)
    print("  VISUAL DISCORD INTEGRATION TEST")
    print("  Testing Threaded Signal Lifecycle Messages")
    print("=" * 70)

    # Create settings with appropriate TEST_MODE based on --mode flag
    settings = get_settings()

    if mode == Mode.live:
        # Force live mode (override TEST_MODE)
        # Note: This requires LIVE_CRYPTO_DISCORD_WEBHOOK_URL and LIVE_STOCK_DISCORD_WEBHOOK_URL
        # to be set in environment or .env
        object.__setattr__(settings, "TEST_MODE", False)
        print("\n⚠️  Mode: LIVE - Routing by asset class")
        print("   CRYPTO signals → LIVE_CRYPTO_DISCORD_WEBHOOK_URL")
        print("   EQUITY signals → LIVE_STOCK_DISCORD_WEBHOOK_URL")
        print("   System messages → TEST_DISCORD_WEBHOOK")
    else:
        print("\n🧪 Mode: TEST - All traffic routes to TEST_DISCORD_WEBHOOK")

    # Initialize client with settings
    client = DiscordClient(settings=settings)

    print(f"⏱️  Update delay: {UPDATE_DELAY_SECONDS}s between messages\n")

    # Run the selected test path
    if path == TestPath.success:
        test_success_path(client)
    elif path == TestPath.invalidation:
        test_invalidation_path(client)
    elif path == TestPath.expiration:
        test_expiration_path(client)
    elif path == TestPath.trail:
        test_runner_trail_path(client)
    elif path == TestPath.short:
        test_short_runner_trail_path(client)
    elif path == TestPath.all:
        run_all_tests(client)

    print("\n" + "=" * 70)
    print("  VISUAL VERIFICATION COMPLETE")
    print("  Please check your Discord channel to verify threading and formatting.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    app()
