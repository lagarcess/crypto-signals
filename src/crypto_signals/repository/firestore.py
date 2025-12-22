"""Firestore Repository for persisting signals."""

import logging
from datetime import datetime, timedelta, timezone

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import Signal, SignalStatus
from google.cloud import firestore

logger = logging.getLogger(__name__)


class SignalRepository:
    """Repository for storing signals in Firestore."""

    def __init__(self):
        """Initialize Firestore client."""
        settings = get_settings()
        self.db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        self.collection_name = "live_signals"

    def save(self, signal: Signal) -> None:
        """
        Save a signal to Firestore.

        Uses signal_id as the document ID for idempotency.
        Serializes the signal with ``model_dump(mode="json")`` so enums and
        datetime-like fields become JSON-compatible values suitable for
        Firestore storage.

        Adds TTL field for automatic cleanup after 30 days.
        Uses native Firestore Timestamp to enable Google's automatic TTL
        policy at the database level.

        Args:
            signal: The signal to save.
        """
        # Convert signal to a JSON-compatible dict for Firestore storage.
        signal_data = signal.model_dump(mode="json")

        # Add TTL timestamp for automatic cleanup (30 days from now)
        # Using datetime (not string) so Firestore stores it as a native Timestamp
        # This enables Google's automatic TTL policy in GCP Console
        ttl_datetime = datetime.now(timezone.utc) + timedelta(days=30)
        signal_data["expireAt"] = ttl_datetime

        doc_ref = self.db.collection(self.collection_name).document(signal.signal_id)
        doc_ref.set(signal_data)

    def get_active_signals(self, symbol: str) -> list[Signal]:
        """
        Get all WAITING signals for a given symbol.
        """
        query = (
            self.db.collection(self.collection_name)
            .where(field_path="symbol", op_string="==", value=symbol)
            .where(
                field_path="status",
                op_string="==",
                value=SignalStatus.WAITING.value,
            )
        )

        results = []
        for doc in query.stream():
            try:
                # Firestore returns dict, Pydantic parses it
                results.append(Signal(**doc.to_dict()))
            except Exception as e:
                logger.error(f"Failed to parse signal {doc.id}: {e}")

        return results

    def update_status(self, signal_id: str, status: SignalStatus) -> None:
        """Update the status of a signal (e.g. to INVALIDATED)."""
        doc_ref = self.db.collection(self.collection_name).document(signal_id)
        doc_ref.update({"status": status.value})

    def cleanup_expired_signals(self, days_old: int = 30) -> int:
        """
        Delete signals older than specified days.

        This provides a manual cleanup mechanism in addition to the TTL field.
        Useful for immediate cleanup or custom retention policies.

        Args:
            days_old: Delete signals older than this many days

        Returns:
            int: Number of signals deleted
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

        logger.info(
            f"Cleaning up signals older than {days_old} days (before {cutoff_date})"
        )

        # Query for old signals
        # Note: We filter on expiration_at which is when the signal was created
        query = self.db.collection(self.collection_name).where(
            field_path="expiration_at", op_string="<", value=cutoff_date
        )

        # Batch delete for efficiency
        batch = self.db.batch()
        count = 0

        for doc in query.stream():
            batch.delete(doc.reference)
            count += 1

            # Firestore batch limit is 500 operations
            if count >= 400:
                batch.commit()
                batch = self.db.batch()
                logger.info(f"Deleted {count} expired signals (batch)")

        # Commit remaining deletes if any
        if count > 0 and count % 400 != 0:
            batch.commit()

        logger.info(f"Cleanup complete: Deleted {count} expired signals")
        return count
