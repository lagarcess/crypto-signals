#!/usr/bin/env python3
"""
Crypto Sentinel - Setup Verification Script.

This script verifies connectivity to all required external services:
- Alpaca Trading API (account status)
- Alpaca Market Data API (latest BTC/USD bar)
- GCP Firestore (write/delete test document)
- GCP BigQuery (dry-run query)
- Discord Webhook (send test message)

Run this script to validate your environment before running the main application.
"""

import sys
from datetime import datetime, timezone

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from google.cloud import bigquery, firestore


def load_settings():
    """
    Load and validate application settings.

    Returns:
        Settings object if successful, None if validation fails
    """
    try:
        from crypto_signals.config import get_settings

        settings = get_settings()
        print("✅ [Configuration] Loaded successfully")
        return settings
    except Exception as e:
        print(f"❌ [Configuration] Failed: {e}")
        return None


def verify_alpaca_trading(settings) -> bool:
    """
    Verify Alpaca Trading API connectivity.

    Fetches account information to confirm API credentials are valid.

    Returns:
        bool: True if connection successful

    Raises:
        Exception: If connection fails
    """
    client = TradingClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
        paper=settings.is_paper_trading,
    )

    account = client.get_account()
    print(f"✅ [Alpaca Trade] Connected (Account Status: {account.status})")
    return True


def verify_alpaca_market_data(settings) -> bool:
    """
    Verify Alpaca Market Data API connectivity.

    Fetches the latest bar for BTC/USD to confirm market data access.

    Returns:
        bool: True if connection successful

    Raises:
        Exception: If connection fails
    """
    client = CryptoHistoricalDataClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
    )

    request = CryptoBarsRequest(
        symbol_or_symbols="BTC/USD",
        timeframe=TimeFrame.Minute,
        limit=1,
    )

    bars = client.get_crypto_bars(request)

    if bars and "BTC/USD" in bars.data:
        latest_bar = bars.data["BTC/USD"][-1]
        print(
            f"✅ [Alpaca Market] Connected (Latest BTC/USD: ${latest_bar.close:,.2f})"
        )
    else:
        print("✅ [Alpaca Market] Connected (No recent bars available)")

    return True


def verify_firestore(settings) -> bool:
    """
    Verify GCP Firestore connectivity.

    Writes a test document to _healthcheck collection and deletes it.

    Returns:
        bool: True if connection successful

    Raises:
        Exception: If connection fails
    """
    db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)

    # Write test document
    doc_ref = db.collection("_healthcheck").document("connection_test")
    doc_ref.set(
        {
            "test": "connection",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    # Delete test document
    doc_ref.delete()

    print("✅ [GCP Firestore] Connected (Write/Delete Test Passed)")
    return True


def verify_bigquery(settings) -> bool:
    """
    Verify GCP BigQuery connectivity.

    Runs a dry-run query (SELECT 1) to confirm BigQuery access.

    Returns:
        bool: True if connection successful

    Raises:
        Exception: If connection fails
    """
    client = bigquery.Client(project=settings.GOOGLE_CLOUD_PROJECT)

    # Configure dry-run job
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)

    # Execute dry-run query
    query_job = client.query("SELECT 1", job_config=job_config)

    # Dry-run returns estimated bytes processed
    print(
        f"✅ [GCP BigQuery] Connected (Dry-run bytes: {query_job.total_bytes_processed})"
    )
    return True


def verify_discord(settings) -> bool:
    """
    Verify Discord Webhook connectivity using DiscordClient.

    Sends a "System Online" notification to the configured webhook.
    Respects MOCK_DISCORD setting.

    Returns:
        bool: True if connection successful (or mock mode active)

    Raises:
        Exception: If connection fails
    """
    if not settings.DISCORD_WEBHOOK_URL and not settings.MOCK_DISCORD:
        print("⚠️ [Discord] Skipped (No URL set)")
        return True

    from crypto_signals.notifications.discord import DiscordClient

    client = DiscordClient(
        webhook_url=settings.DISCORD_WEBHOOK_URL, mock_mode=settings.MOCK_DISCORD
    )

    msg = "✅ [Health Check] System is online and connected."
    client.send_message(msg)

    status = "Mocked" if settings.MOCK_DISCORD else "Sent"
    print(f"✅ [Discord] Connected ({status})")
    return True


def run_all_verifications() -> bool:
    """
    Run all service verifications.

    Returns:
        bool: True if all verifications pass, False otherwise
    """
    print()
    print("🔍 Checking Services...")
    print()

    # Step 1: Load configuration
    settings = load_settings()
    if settings is None:
        print()
        print("❌ Cannot proceed without valid configuration.")
        print("   Please check your .env file and environment variables.")
        return False

    # Step 2: Run individual service checks
    verifications = [
        ("Alpaca Market", verify_alpaca_market_data),
        ("Alpaca Trade", verify_alpaca_trading),
        ("GCP Firestore", verify_firestore),
        ("GCP BigQuery", verify_bigquery),
        ("Discord", verify_discord),
    ]

    all_passed = True

    for service_name, verify_func in verifications:
        try:
            verify_func(settings)
        except Exception as e:
            print(f"❌ [{service_name}] Failed: {e}")
            all_passed = False

    print()

    if all_passed:
        print("✅ All verifications passed! System ready.")
    else:
        print("⚠️  Some verifications failed. Please check the errors above.")

    return all_passed


if __name__ == "__main__":
    success = run_all_verifications()
    sys.exit(0 if success else 1)
