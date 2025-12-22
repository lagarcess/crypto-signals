"""
Main Application Entrypoint.

This script executes the signal generation pipeline for a defined portfolio of assets.
It orchestrates data fetching, pattern recognition, persistence, and notifications.
"""

import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from crypto_signals.config import (
    get_crypto_data_client,
    get_settings,
    get_stock_data_client,
    load_config_from_firestore,
)
from crypto_signals.domain.schemas import AssetClass, ExitReason, SignalStatus
from crypto_signals.engine.signal_generator import SignalGenerator
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.notifications.discord import DiscordClient
from crypto_signals.observability import get_metrics_collector, log_execution_time
from crypto_signals.repository.firestore import SignalRepository
from crypto_signals.secrets_manager import init_secrets

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_requested = True


def main():
    """Execute the main signal generation loop."""
    global shutdown_requested

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Get metrics collector
    metrics = get_metrics_collector()

    logger.info("Starting Crypto Sentinel Signal Generator...")
    app_start_time = time.time()

    try:
        # Initialize Secrets
        logger.info("Loading secrets...")
        with log_execution_time(logger, "load_secrets"):
            if not init_secrets():
                logger.critical("Failed to load required secrets. Exiting.")
                sys.exit(1)

            # Initialize Services
            logger.info("Initializing services...")
            with log_execution_time(logger, "initialize_services"):
                stock_client = get_stock_data_client()
                crypto_client = get_crypto_data_client()
                market_provider = MarketDataProvider(stock_client, crypto_client)
                generator = SignalGenerator(market_provider=market_provider)
                repo = SignalRepository()
                discord = DiscordClient()

        # 2. Define Portfolio
        settings = get_settings()

        # Dynamic Config Loading
        firestore_config = load_config_from_firestore()

        if firestore_config:
            logger.info("Using configuration from Firestore (overriding .env)")
            if "CRYPTO_SYMBOLS" in firestore_config:
                settings.CRYPTO_SYMBOLS = firestore_config["CRYPTO_SYMBOLS"]

            # Note: Equity restriction is handled in config.py
        else:
            logger.info("Using configuration from .env")

        portfolio_items = []
        for s in settings.CRYPTO_SYMBOLS:
            portfolio_items.append((s, AssetClass.CRYPTO))
        for s in settings.EQUITY_SYMBOLS:
            portfolio_items.append((s, AssetClass.EQUITY))

        logger.info(f"Processing {len(portfolio_items)} symbols...")

        # Get rate limit delay from settings (default 0.5 seconds between requests)
        # Alpaca has 200 req/min limit = 1 req per 0.3s minimum
        # We use 0.5s for safety margin
        rate_limit_delay = getattr(settings, "RATE_LIMIT_DELAY", 0.5)

        # 3. Execution Loop
        signals_found = 0
        symbols_processed = 0
        errors_encountered = 0

        for idx, (symbol, asset_class) in enumerate(portfolio_items):
            # Check for shutdown signal
            if shutdown_requested:
                logger.info("Shutdown requested. Stopping processing gracefully...")
                break

            symbol_start_time = time.time()

            try:
                # Rate limiting: Add delay between symbols (except first)
                if idx > 0:
                    logger.debug(f"Rate limit delay: {rate_limit_delay}s")
                    time.sleep(rate_limit_delay)

                logger.info(
                    f"Analyzing {symbol} ({asset_class.value})...",
                    extra={"symbol": symbol, "asset_class": asset_class.value},
                )

                # Fetch Data ONCE
                try:
                    df = market_provider.get_daily_bars(
                        symbol, asset_class, lookback_days=365
                    )
                except Exception as e:
                    logger.error(f"Failed to fetch data for {symbol}: {e}")
                    continue

                if df.empty:
                    logger.warning(f"No data for {symbol}")
                    continue

                # Generate Signals
                trade_signal = generator.generate_signals(
                    symbol, asset_class, dataframe=df
                )

                # Track metrics
                symbol_duration = time.time() - symbol_start_time
                symbols_processed += 1

                if trade_signal:
                    signals_found += 1
                    logger.info(
                        f"SIGNAL FOUND: {trade_signal.pattern_name} "
                        f"on {trade_signal.symbol}",
                        extra={
                            "symbol": trade_signal.symbol,
                            "pattern": trade_signal.pattern_name,
                            "stop_loss": trade_signal.suggested_stop,
                        },
                    )

                    # Persist
                    repo.save(trade_signal)
                    logger.info("Signal saved to Firestore.")

                    # Notify
                    if not discord.send_signal(trade_signal):
                        logger.warning(
                            "Failed to send Discord notification for "
                            f"{trade_signal.symbol}",
                            extra={"symbol": trade_signal.symbol},
                        )

                    metrics.record_success("signal_generation", symbol_duration)
                else:
                    logger.debug(f"No signal for {symbol}.")
                    metrics.record_success("signal_generation", symbol_duration)

                # Active Trade Validation
                # Check for updates on existing WAITING/ACTIVE signals
                active_signals = repo.get_active_signals(symbol)
                if active_signals:
                    logger.info(
                        f"Checking active signals for {symbol} ({len(active_signals)})..."
                    )

                    # 1. Run Expiration Check (24h Rule)
                    now_utc = datetime.now(timezone.utc)
                    today_date = now_utc.date()

                    # Check exits first
                    exited_signals = generator.check_exits(
                        active_signals, symbol, asset_class, dataframe=df
                    )

                    # Process Exits (TP / Invalidation)
                    for exited in exited_signals:
                        logger.info(
                            f"SIGNAL UPDATE: {exited.signal_id} "
                            f"status -> {exited.status}",
                            extra={
                                "symbol": symbol,
                                "signal_id": exited.signal_id,
                                "new_status": exited.status,
                            },
                        )
                        repo.update_signal(exited)

                        # Notify Discord of Status Change
                        status_emoji = {
                            SignalStatus.INVALIDATED: "🚫",
                            SignalStatus.TP1_HIT: "🎯",
                            SignalStatus.TP2_HIT: "🚀",
                            SignalStatus.TP3_HIT: "🌕",
                            SignalStatus.EXPIRED: "⏳",
                        }.get(exited.status, "ℹ️")

                        msg = (
                            f"{status_emoji} **SIGNAL UPDATE: {symbol}** {status_emoji}\n"
                            f"**Status**: {exited.status.value}\n"
                            f"**Pattern**: {exited.pattern_name}\n"
                        )

                        if exited.exit_reason:
                            msg += f"**Reason**: {exited.exit_reason}\n"

                        if exited.status == SignalStatus.TP1_HIT:
                            msg += (
                                "ℹ️ **Action**: Scaling Out (50%) & Stop -> **Breakeven**"
                            )

                        discord.send_message(msg)

                        # Remove exited signals from expiration checking
                        if exited in active_signals:
                            active_signals.remove(exited)

                    # 2. Expiration Check on REMAINING Waiting signals
                    for sig in active_signals:
                        # Only expire WAITING signals.
                        # If TP1_HIT, it's active.
                        if sig.status != SignalStatus.WAITING:
                            continue

                        cutoff_date = sig.ds + timedelta(days=1)
                        if today_date > cutoff_date:
                            logger.info(
                                f"EXPIRING Signal {sig.signal_id} (Date: {sig.ds})",
                                extra={"symbol": symbol, "signal_id": sig.signal_id},
                            )
                            sig.status = SignalStatus.EXPIRED
                            sig.exit_reason = ExitReason.EXPIRED
                            repo.update_signal(sig)
                            discord.send_message(
                                f"⏳ **SIGNAL EXPIRED: {symbol}** ⏳\n"
                                f"Signal from {sig.ds} expired (24h Limit)."
                            )

            except Exception as e:
                errors_encountered += 1
                symbol_duration = time.time() - symbol_start_time
                metrics.record_failure("signal_generation", symbol_duration)
                logger.error(
                    f"Error processing {symbol} ({asset_class.value}): {e}",
                    exc_info=True,
                    extra={"symbol": symbol, "asset_class": asset_class.value},
                )
                # Continue to next symbol despite error
                continue

        # Log execution summary
        total_duration = time.time() - app_start_time
        logger.info("=== EXECUTION SUMMARY ===")
        logger.info(f"Total duration: {total_duration:.2f}s")
        logger.info(f"Symbols processed: {symbols_processed}/{len(portfolio_items)}")
        logger.info(f"Signals found: {signals_found}")
        logger.info(f"Errors encountered: {errors_encountered}")

        # Log detailed metrics
        metrics.log_summary(logger)

        if shutdown_requested:
            logger.info("Signal generation cycle interrupted by shutdown request.")
        else:
            logger.info("Signal generation cycle complete.")

    except Exception as e:
        logger.critical(f"Fatal error in main application loop: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
