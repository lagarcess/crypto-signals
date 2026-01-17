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

from crypto_signals.repository.firestore import RejectedSignalRepository, SignalRepository
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

        # Initialize repositories
        signal_repo = SignalRepository()
        rejected_repo = RejectedSignalRepository()

        if args.flush_all:
            logger.warning(
                f"⚠️  FLUSH ALL MODE - Deleting all signals in {signal_repo.collection_name} and {rejected_repo.collection_name}!"
            )

            if not args.force:
                confirm = input(
                    "Are you sure you want to delete ALL signals? Type 'YES' to confirm: "
                )
                if confirm != "YES":
                    logger.info("Flush cancelled by user.")
                    sys.exit(0)

            deleted_signals = signal_repo.flush_all_signals()
            # Note: We currently only flush 'live_signals' (or 'test_signals') in flush-all mode.
            # Rejected signals are less critical to manually flush, but can be added here if needed.
            logger.info(f"Flush complete. Deleted {deleted_signals} signals.")
        else:
            # Default cleanup behavior
            logger.info(
                f"Starting Firestore cleanup job (Env: {signal_repo.collection_name})..."
            )
            deleted_signals = signal_repo.cleanup_expired_signals()
            deleted_rejected = rejected_repo.cleanup_expired()
            logger.info(
                f"Cleanup job complete: {deleted_signals} signals, {deleted_rejected} rejected signals."
            )

        sys.exit(0)

    except Exception as e:
        logger.critical(f"Cleanup job failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
