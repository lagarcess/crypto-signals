"""
Main Application Entrypoint.

This script executes the signal generation pipeline for a defined portfolio of assets.
It orchestrates data fetching, pattern recognition, persistence, and notifications.
"""

import logging
import signal
import sys
import time

from crypto_signals.config import (
    get_crypto_data_client,
    get_settings,
    get_stock_data_client,
)
from crypto_signals.domain.schemas import AssetClass
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
        # 0. Initialize Secrets (must be first)
        logger.info("Loading secrets...")
        with log_execution_time(logger, "load_secrets"):
            if not init_secrets():
                logger.critical("Failed to load required secrets. Exiting.")
                sys.exit(1)

        # 1. Initialize Dependencies
        logger.info("Initializing services...")
        with log_execution_time(logger, "initialize_services"):

        # Market Data
        stock_client = get_stock_data_client()
        crypto_client = get_crypto_data_client()
        market_provider = MarketDataProvider(stock_client, crypto_client)

        # Engine
        generator = SignalGenerator(market_provider=market_provider)

        # Persistence & Notifications
        repo = SignalRepository()
        discord = DiscordClient()  # Config handles URL and Mock Mode automatically

        # 2. Define Portfolio
        settings = get_settings()
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

                # Generate Signals
                signal = generator.generate_signals(symbol, asset_class)

                # Track metrics
                symbol_duration = time.time() - symbol_start_time
                symbols_processed += 1

                if signal:
                    signals_found += 1
                    logger.info(
                        f"SIGNAL FOUND: {signal.pattern_name} on {signal.symbol}",
                        extra={
                            "symbol": signal.symbol,
                            "pattern": signal.pattern_name,
                            "stop_loss": signal.suggested_stop,
                        },
                    )

                    # Persist
                    repo.save(signal)
                    logger.info("Signal saved to Firestore.")

                    # Notify
                    if not discord.send_signal(signal):
                        logger.warning(
                            f"Failed to send Discord notification for {signal.symbol}",
                            extra={"symbol": signal.symbol},
                        )

                    metrics.record_success("signal_generation", symbol_duration)
                else:
                    logger.info(f"No signal for {symbol}.")
                    metrics.record_success("signal_generation", symbol_duration)

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
