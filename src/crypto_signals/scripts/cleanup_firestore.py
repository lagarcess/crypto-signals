#!/usr/bin/env python3
"""
Firestore Cleanup Script.

This script cleans up expired signals from Firestore to prevent unlimited
data accumulation and manage storage costs. It should be run periodically
(e.g., daily via cron or Cloud Scheduler).
"""

import logging
import sys

from crypto_signals.repository.firestore import SignalRepository
from crypto_signals.secrets_manager import init_secrets

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    """Execute the cleanup job."""
    logger.info("Starting Firestore cleanup job...")

    try:
        # Initialize secrets
        if not init_secrets():
            logger.critical("Failed to load required secrets. Exiting.")
            sys.exit(1)

        # Initialize repository
        repo = SignalRepository()

        # Clean up signals older than 30 days
        deleted_count = repo.cleanup_expired_signals(days_old=30)

        logger.info(f"Cleanup job complete. Deleted {deleted_count} expired signals.")
        sys.exit(0)

    except Exception as e:
        logger.critical(f"Cleanup job failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
