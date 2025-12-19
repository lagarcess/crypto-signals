"""
Main Application Entrypoint.

This script executes the signal generation pipeline for a defined portfolio of assets.
It orchestrates data fetching, pattern recognition, persistence, and notifications.
"""

import logging
import sys
from typing import List

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    """Execute the main signal generation loop."""
    logger.info("Starting Crypto Sentinel Signal Generator...")

    try:
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
        portfolio: List[str] = get_settings().PORTFOLIO

        logger.info(f"Processing portfolio: {portfolio}")

        # 3. Execution Loop
        for symbol in portfolio:
            try:
                # Smart Asset Detection
                if "/" in symbol:
                    asset_class = AssetClass.CRYPTO
                else:
                    asset_class = AssetClass.EQUITY

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
                    discord.send_signal(signal)
                else:
                    logger.info(f"No signal for {symbol}.")

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)
                # Continue to next symbol despite error
                continue

        logger.info("Signal generation cycle complete.")

    except Exception as e:
        logger.critical(f"Fatal error in main application loop: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
