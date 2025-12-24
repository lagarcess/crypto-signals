"""Firestore Repository for persisting signals and positions."""

from datetime import datetime, timedelta, timezone

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import Position, Signal, SignalStatus, TradeStatus
from crypto_signals.observability import log_validation_error
from google.cloud import firestore
from google.cloud.firestore import FieldFilter
from loguru import logger
from pydantic import ValidationError


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
            except ValidationError as e:
                # Display Rich error panel for database drift
                log_validation_error(doc.id, e)
                # Auto-delete invalid legacy document
                doc.reference.delete()
                logger.info(f"Deleted invalid legacy signal: {doc.id}")

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

    def flush_all_signals(self) -> int:
        """Delete ALL signals in the collection. Use with caution!

        Returns:
            int: Number of documents deleted.
        """
        logger.warning("FLUSH ALL: Deleting all documents from live_signals collection")

        # Batch delete for efficiency
        batch = self.db.batch()
        count = 0

        for doc in self.db.collection(self.collection_name).stream():
            batch.delete(doc.reference)
            count += 1

            # Firestore batch limit is 500 operations
            if count >= 400:
                batch.commit()
                batch = self.db.batch()
                logger.info(f"Flushed {count} signals (batch)")

        # Commit remaining deletes if any
        if count > 0 and count % 400 != 0:
            batch.commit()

        logger.warning(f"FLUSH ALL complete: Deleted {count} total signals")
        return count


class PositionRepository:
    """Repository for storing positions in Firestore."""

    def __init__(self):
        """Initialize Firestore client."""
        settings = get_settings()
        self.db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        self.collection_name = "live_positions"

    def save(self, position: Position) -> None:
        """
        Save a position to Firestore.

        Uses position_id as document ID for idempotency with Alpaca order IDs.
        Only sets created_at on new documents to preserve original timestamp.
        """
        doc_ref = self.db.collection(self.collection_name).document(position.position_id)

        # Check if document exists to preserve created_at
        doc = doc_ref.get()
        position_data = position.model_dump(mode="json")

        if doc.exists:
            # Update existing document, preserve created_at
            position_data["updated_at"] = datetime.now(timezone.utc)
        else:
            # New document, set created_at
            position_data["created_at"] = datetime.now(timezone.utc)

        doc_ref.set(position_data, merge=True)
        logger.info(
            f"Position {position.position_id} saved to Firestore",
            extra={
                "position_id": position.position_id,
                "signal_id": position.signal_id,
                "status": position.status.value,
            },
        )

    def get_open_positions(self) -> list[Position]:
        """Get all OPEN positions."""
        query = self.db.collection(self.collection_name).where(
            filter=FieldFilter("status", "==", TradeStatus.OPEN.value)
        )

        results = []
        for doc in query.stream():
            try:
                results.append(Position(**doc.to_dict()))
            except ValidationError as e:
                log_validation_error(doc.id, e)
                logger.warning(f"Skipped invalid position document: {doc.id}")

        return results

    def get_position_by_signal(self, signal_id: str) -> Position | None:
        """Get position by its originating signal ID."""
        query = (
            self.db.collection(self.collection_name)
            .where(filter=FieldFilter("signal_id", "==", signal_id))
            .limit(1)
        )

        for doc in query.stream():
            try:
                return Position(**doc.to_dict())
            except ValidationError as e:
                log_validation_error(doc.id, e)
                return None

        return None

    def update_position(self, position: Position) -> None:
        """Update an existing position in Firestore."""
        doc_ref = self.db.collection(self.collection_name).document(position.position_id)
        position_data = position.model_dump(mode="json")
        position_data["updated_at"] = datetime.now(timezone.utc)
        doc_ref.set(position_data, merge=True)
