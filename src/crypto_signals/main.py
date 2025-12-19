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

    logger.info("Starting Crypto Sentinel Signal Generator...")

    try:
        # 0. Initialize Secrets (must be first)
        logger.info("Loading secrets...")
        if not init_secrets():
            logger.critical("Failed to load required secrets. Exiting.")
            sys.exit(1)

        # 1. Initialize Dependencies
        logger.info("Initializing services...")

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
        for idx, (symbol, asset_class) in enumerate(portfolio_items):
            # Check for shutdown signal
            if shutdown_requested:
                logger.info("Shutdown requested. Stopping processing gracefully...")
                break

            try:
                # Rate limiting: Add delay between symbols (except first)
                if idx > 0:
                    logger.debug(f"Rate limit delay: {rate_limit_delay}s")
                    time.sleep(rate_limit_delay)

                logger.info(f"Analyzing {symbol} ({asset_class.value})...")

                # Generate Signals
                signal = generator.generate_signals(symbol, asset_class)

                if signal:
                    logger.info(
                        f"SIGNAL FOUND: {signal.pattern_name} on {signal.symbol}"
                    )

                    # Persist
                    repo.save(signal)
                    logger.info("Signal saved to Firestore.")

                    # Notify
                    if not discord.send_signal(signal):
                        logger.warning(
                            f"Failed to send Discord notification for {signal.symbol}"
                        )
                else:
                    logger.info(f"No signal for {symbol}.")

            except Exception as e:
                logger.error(
                    f"Error processing {symbol} ({asset_class.value}): {e}",
                    exc_info=True,
                )
                # Continue to next symbol despite error
                continue

        if shutdown_requested:
            logger.info("Signal generation cycle interrupted by shutdown request.")
        else:
            logger.info("Signal generation cycle complete.")

    except Exception as e:
        logger.critical(f"Fatal error in main application loop: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
