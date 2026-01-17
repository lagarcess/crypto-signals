"""Firestore Repository for persisting signals and positions.

Dev Note: Enable GCP native TTL policy with:
  gcloud firestore fields ttls update delete_at --collection-group=live_signals --enable-ttl
  gcloud firestore fields ttls update delete_at --collection-group=rejected_signals --enable-ttl
"""

from datetime import datetime, timedelta, timezone

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import Position, Signal, SignalStatus, TradeStatus
from crypto_signals.observability import log_validation_error
from google.cloud import firestore
from google.cloud.firestore import FieldFilter
from loguru import logger
from pydantic import ValidationError


class JobLockRepository:
    """Repository for managing distributed job locks."""

    def __init__(self):
        """Initialize Firestore client."""
        settings = get_settings()
        self.db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        self.collection_name = "job_locks"

    def acquire_lock(self, job_id: str, ttl_minutes: int = 10) -> bool:
        """
        Attempt to acquire a distributed lock.

        Args:
            job_id: Unique identifier for the job (e.g., 'signal_generation_cron').
            ttl_minutes: Time-to-live for the lock in minutes.

        Returns:
            bool: True if lock acquired, False if already held by another valid instance.
        """
        doc_ref = self.db.collection(self.collection_name).document(job_id)

        @firestore.transactional
        def _acquire_in_transaction(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            now = datetime.now(timezone.utc)

            if snapshot.exists:
                data = snapshot.to_dict()
                expire_at = data.get("expire_at")
                # Ensure we handle timezone-aware datetimes correctly
                if expire_at:
                    if expire_at > now:
                        return False  # Lock still valid

            # Create or overwrite lock
            new_expiry = now + timedelta(minutes=ttl_minutes)
            transaction.set(
                doc_ref,
                {"locked_at": now, "expire_at": new_expiry, "job_id": job_id},
            )
            return True

        try:
            return _acquire_in_transaction(self.db.transaction())
        except Exception as e:
            logger.error(f"Failed to acquire lock for {job_id}: {e}")
            return False

    def release_lock(self, job_id: str) -> None:
        """Release the job lock."""
        try:
            self.db.collection(self.collection_name).document(job_id).delete()
            logger.info(f"Released lock for {job_id}")
        except Exception as e:
            logger.error(f"Failed to release lock for {job_id}: {e}")


class SignalRepository:
    """Repository for storing signals in Firestore."""

    def __init__(self):
        """Initialize Firestore client."""
        self.settings = get_settings()
        self.db = firestore.Client(project=self.settings.GOOGLE_CLOUD_PROJECT)
        self.collection_name = "live_signals"

    DEFAULT_TTL_DAYS = 30

    def save(self, signal: Signal) -> None:
        """Save a signal to Firestore.

        Note: delete_at is already populated by SignalGenerator (30-day TTL).
        """
        signal_data = signal.model_dump(mode="json")
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

                # Auto-delete invalid legacy document if enabled
                if self.settings.CLEANUP_ON_FAILURE:
                    doc.reference.delete()
                    logger.info(f"Auto-deleted invalid legacy signal: {doc.id}")
                else:
                    logger.warning(
                        f"Skipping invalid signal: {doc.id} (cleanup disabled)"
                    )

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

    def get_by_id(self, signal_id: str) -> Signal | None:
        """
        Get a signal by its ID.

        Args:
            signal_id: The unique signal identifier.

        Returns:
            Signal object if found, None otherwise.
        """
        doc = self.db.collection(self.collection_name).document(signal_id).get()
        if doc.exists:
            try:
                return Signal(**doc.to_dict())
            except ValidationError as e:
                log_validation_error(doc.id, e)

                # Auto-delete invalid legacy document if enabled
                if self.settings.CLEANUP_ON_FAILURE:
                    doc.reference.delete()
                    logger.info(f"Auto-deleted invalid legacy signal: {doc.id}")

                return None
        return None

    def update_signal_atomic(self, signal_id: str, updates: dict) -> bool:
        """
        Atomically update signal fields using Firestore transaction.

        Use for status changes where race conditions are possible
        (e.g., concurrent signal processing runs).

        Args:
            signal_id: The signal ID to update.
            updates: Dictionary of field updates.

        Returns:
            bool: True if update succeeded, False otherwise.
        """
        doc_ref = self.db.collection(self.collection_name).document(signal_id)

        @firestore.transactional
        def update_in_transaction(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                return False
            transaction.update(doc_ref, updates)
            return True

        try:
            return update_in_transaction(self.db.transaction())
        except Exception as e:
            logger.error(f"Atomic update failed for {signal_id}: {e}")
            return False

    def cleanup_expired_signals(self) -> int:
        """Delete signals past their TTL. Returns count deleted.

        Uses delete_at field for native GCP TTL support. Queries for signals where
        delete_at < now (signals past their physical TTL are cleaned up).

        Note: The delete_at field is set to 30 days for live signals and 7 days
        for rejected signals when they are created.
        """
        cutoff_date = datetime.now(timezone.utc)

        logger.info(f"Cleaning up signals with delete_at before {cutoff_date}")

        query = self.db.collection(self.collection_name).where(
            filter=FieldFilter("delete_at", "<", cutoff_date)
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

    def purge_poison_signals(self) -> int:
        """
        Scan the entire collection and delete documents that fail validation.

        This is a diagnostic cleanup tool. Use with caution.

        Returns:
            int: Number of documents purged.
        """
        logger.info(f"Starting purge of poison signals in '{self.collection_name}'...")

        count = 0
        batch = self.db.batch()

        # Scan ALL documents (expensive operation, use sparingly)
        for doc in self.db.collection(self.collection_name).stream():
            try:
                # Attempt to validate
                Signal(**doc.to_dict())
            except ValidationError:
                # Found a poison document
                batch.delete(doc.reference)
                count += 1

                if count >= 400:
                    batch.commit()
                    batch = self.db.batch()
                    logger.info(f"Purged {count} poison signals (batch)")

        if count > 0 and count % 400 != 0:
            batch.commit()

        if count > 0:
            logger.info(f"Purge complete: Deleted {count} poison signals")
        else:
            logger.info("No poison signals found during purge.")

        return count


class RejectedSignalRepository:
    """Repository for storing rejected (shadow) signals in Firestore.

    Shadow signals are patterns that were detected but failed quality gates
    (e.g., Volume < 1.5x, R:R < 1.5). They are persisted for:
    - Backtesting analysis (Phase 8)
    - Filter optimization
    - Market regime analysis

    Uses a shorter 7-day TTL since shadow signals are primarily for debugging
    and analysis, not operational trading.
    """

    # Shadow signals expire after 7 days (shorter than live signals)
    DEFAULT_TTL_DAYS = 7

    def __init__(self):
        """Initialize Firestore client."""
        settings = get_settings()
        self.db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        self.collection_name = "rejected_signals"

    def save(self, signal: Signal) -> None:
        """Save a rejected signal to Firestore with 7-day TTL.

        Args:
            signal: Signal with status=REJECTED_BY_FILTER and rejection_reason populated
        """
        if signal.status != SignalStatus.REJECTED_BY_FILTER:
            logger.warning(
                f"RejectedSignalRepository.save() called with non-rejected signal: "
                f"{signal.signal_id} (status={signal.status})"
            )
            return

        signal_data = signal.model_dump(mode="json")
        # rejected_at is set here (repository-level metadata)
        # delete_at is already set by SignalGenerator (7-day TTL for rejected signals)
        signal_data["rejected_at"] = datetime.now(timezone.utc)

        doc_ref = self.db.collection(self.collection_name).document(signal.signal_id)
        doc_ref.set(signal_data)

        logger.debug(
            f"[SHADOW] Saved rejected signal: {signal.symbol} {signal.pattern_name} - "
            f"{signal.rejection_reason}"
        )

    def get_rejections_by_symbol(self, symbol: str, days: int = 7) -> list[Signal]:
        """Get recent rejected signals for a symbol.

        Useful for analyzing which patterns are being filtered most often.

        Args:
            symbol: Trading symbol (e.g., "BTC/USD")
            days: Look back period in days (default: 7)

        Returns:
            List of rejected Signal objects
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        query = (
            self.db.collection(self.collection_name)
            .where(filter=FieldFilter("symbol", "==", symbol))
            .where(filter=FieldFilter("rejected_at", ">=", cutoff))
        )

        results = []
        for doc in query.stream():
            try:
                results.append(Signal(**doc.to_dict()))
            except ValidationError as e:
                log_validation_error(doc.id, e)
                # Auto-delete invalid legacy document
                doc.reference.delete()

        return results

    def get_rejection_stats(self, days: int = 7) -> dict[str, int]:
        """Get aggregated rejection counts by reason.

        Returns:
            Dict mapping rejection_reason to count
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        query = self.db.collection(self.collection_name).where(
            filter=FieldFilter("rejected_at", ">=", cutoff)
        )

        stats: dict[str, int] = {}
        for doc in query.stream():
            data = doc.to_dict()
            reason = data.get("rejection_reason", "Unknown")
            stats[reason] = stats.get(reason, 0) + 1

        return stats

    def cleanup_expired(self) -> int:
        """Delete expired rejected signals. Returns count deleted.

        Uses delete_at field for native GCP TTL support.
        """
        cutoff_date = datetime.now(timezone.utc)

        query = self.db.collection(self.collection_name).where(
            filter=FieldFilter("delete_at", "<", cutoff_date)
        )

        batch = self.db.batch()
        count = 0

        for doc in query.stream():
            batch.delete(doc.reference)
            count += 1

            if count >= 400:
                batch.commit()
                batch = self.db.batch()

        if count > 0 and count % 400 != 0:
            batch.commit()

        if count > 0:
            logger.info(f"Cleaned up {count} expired rejected signals")

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
