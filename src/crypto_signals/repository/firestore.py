"""Firestore Repository for persisting signals."""

from google.cloud import firestore

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import Signal


class SignalRepository:
    """Repository for storing signals in Firestore."""

    def __init__(self):
        """Initialize Firestore client."""
        settings = get_settings()
        self.db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        self.collection_name = "generated_signals"

    def save(self, signal: Signal) -> None:
        """
        Save a signal to Firestore.

        Uses signal_id as the document ID for idempotency.

        Args:
            signal: The signal to save.
        """
        # Convert to dict, ensuring enums are strings and dates are serialized if needed
        # mode='json' converts types to JSON-compatible (strings for dates, enums)
        # However, for Firestore, maintaining datetime objects is often preferred for
        # expiration_at
        # But for 'ds' (date), string is acceptable.
        # Let's use mode='json' to be safe with Enums and ensure compatibility.
        signal_data = signal.model_dump(mode="json")

        doc_ref = self.db.collection(self.collection_name).document(signal.signal_id)
        doc_ref.set(signal_data)
