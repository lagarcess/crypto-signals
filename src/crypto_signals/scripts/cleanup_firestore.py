#!/usr/bin/env python3
"""
Firestore Cleanup Script.

This script cleans up expired signals from Firestore to prevent unlimited
data accumulation and manage storage costs. It should be run periodically
(e.g., daily via cron or Cloud Scheduler).

Commands:
    --cleanup     (default) Delete signals older than 30 days
    --flush-all   Delete ALL signals (use with caution!)
"""

import argparse
import sys

from loguru import logger

from crypto_signals.repository.firestore import SignalRepository
from crypto_signals.secrets_manager import init_secrets

# Configure logging (optional if main configures it, but this is a script)
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss,SSS} - {name} - {level} - {message}",
    level="INFO",
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Firestore signals cleanup utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--cleanup",
        action="store_true",
        default=True,
        help="Delete signals older than 30 days (default behavior)",
    )
    group.add_argument(
        "--flush-all",
        action="store_true",
        help="Delete ALL signals in the collection (DANGEROUS - use with caution!)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt for flush-all",
    )

    return parser.parse_args()


def main():
    """Execute the cleanup job."""
    args = parse_args()

    try:
        # Initialize secrets
        if not init_secrets():
            logger.critical("Failed to load required secrets. Exiting.")
            sys.exit(1)

        # Initialize repository
        repo = SignalRepository()

        if args.flush_all:
            logger.warning("⚠️  FLUSH ALL MODE - This will delete ALL signals!")

            if not args.force:
                confirm = input(
                    "Are you sure you want to delete ALL signals? Type 'YES' to confirm: "
                )
                if confirm != "YES":
                    logger.info("Flush cancelled by user.")
                    sys.exit(0)

            deleted_count = repo.flush_all_signals()
            logger.info(f"Flush complete. Deleted {deleted_count} signals.")
        else:
            # Default cleanup behavior
            logger.info("Starting Firestore cleanup job...")
            deleted_count = repo.cleanup_expired_signals(days_old=30)
            logger.info(f"Cleanup job complete. Deleted {deleted_count} expired signals.")

        sys.exit(0)

    except Exception as e:
        logger.critical(f"Cleanup job failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
