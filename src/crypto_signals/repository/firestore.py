"""Firestore Repository for persisting signals."""

from datetime import datetime, timedelta, timezone

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import Signal, SignalStatus
from google.cloud import firestore
from google.cloud.firestore import FieldFilter
from loguru import logger


class SignalRepository:
    """Repository for storing signals in Firestore."""

    def __init__(self):
        """Initialize Firestore client."""
        settings = get_settings()
        self.db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        self.collection_name = "live_signals"

    def save(self, signal: Signal) -> None:
        """Save a signal to Firestore with 30-day TTL."""
        signal_data = signal.model_dump(mode="json")
        signal_data["expireAt"] = datetime.now(timezone.utc) + timedelta(days=30)

        doc_ref = self.db.collection(self.collection_name).document(signal.signal_id)
        doc_ref.set(signal_data)

    def get_active_signals(self, symbol: str) -> list[Signal]:
        """
        Get all ACTIVE signals for a given symbol.

        Active statuses: WAITING, TP1_HIT, TP2_HIT.
        """
        # Firestore 'in' query allows up to 10 values
        active_statuses = [
            SignalStatus.WAITING.value,
            SignalStatus.TP1_HIT.value,
            SignalStatus.TP2_HIT.value,
        ]

        query = (
            self.db.collection(self.collection_name)
            .where(filter=FieldFilter("symbol", "==", symbol))
            .where(filter=FieldFilter("status", "in", active_statuses))
        )

        results = []
        for doc in query.stream():
            try:
                results.append(Signal(**doc.to_dict()))
            except Exception as e:
                logger.error(f"Failed to parse signal {doc.id}: {e}")

        return results

    def update_signal(self, signal: Signal) -> None:
        """Update an existing signal in Firestore (merged update)."""
        doc_ref = self.db.collection(self.collection_name).document(signal.signal_id)
        signal_data = signal.model_dump(mode="json")
        doc_ref.set(signal_data, merge=True)

    def update_status(self, signal_id: str, status: SignalStatus) -> None:
        """Update only the status of a signal (Legacy method)."""
        doc_ref = self.db.collection(self.collection_name).document(signal_id)
        doc_ref.update({"status": status.value})

    def cleanup_expired_signals(self, days_old: int = 30) -> int:
        """Delete signals older than specified days. Returns count deleted."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        logger.info(f"Cleaning up signals before {cutoff_date}")

        query = self.db.collection(self.collection_name).where(
            filter=FieldFilter("expiration_at", "<", cutoff_date)
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
