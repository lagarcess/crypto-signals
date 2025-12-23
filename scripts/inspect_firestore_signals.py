#!/usr/bin/env python3
"""
Firestore Signals Inspection Script.

This script inspects the live_signals collection in Firestore to identify
legacy documents that may be missing required fields (asset_class, entry_price).
Use this to diagnose "poison" records before enabling cleanup-on-failure.
"""

import sys
from collections import Counter

from crypto_signals.config import get_settings
from crypto_signals.secrets_manager import init_secrets
from google.cloud import firestore
from loguru import logger

# Configure logging
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss,SSS} - {name} - {level} - {message}",
    level="INFO",
)

# Required fields for Signal model validation
REQUIRED_FIELDS = {
    "signal_id",
    "ds",
    "strategy_id",
    "symbol",
    "asset_class",
    "entry_price",
    "pattern_name",
    "suggested_stop",
}


def main():
    """Inspect all documents in live_signals collection."""
    logger.info("Starting Firestore signals inspection...")

    # Initialize secrets
    if not init_secrets():
        logger.critical("Failed to load required secrets. Exiting.")
        sys.exit(1)

    try:
        # Initialize Firestore client
        settings = get_settings()
        db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        collection_name = "live_signals"

        # Query all documents
        docs = list(db.collection(collection_name).stream())
        total_count = len(docs)
        logger.info(f"Total documents in '{collection_name}': {total_count}")

        if total_count == 0:
            logger.info("Collection is empty. No documents to inspect.")
            sys.exit(0)

        # Analyze documents
        missing_fields_counter = Counter()
        poison_docs = []

        for doc in docs:
            data = doc.to_dict()
            doc_fields = set(data.keys())
            missing = REQUIRED_FIELDS - doc_fields

            logger.info(f"\n📄 Document ID: {doc.id}")
            logger.info(f"   Fields present: {sorted(doc_fields)}")

            if missing:
                logger.warning(f"   ⚠️  Missing required fields: {sorted(missing)}")
                poison_docs.append({"id": doc.id, "missing": missing})
                for field in missing:
                    missing_fields_counter[field] += 1
            else:
                logger.info("   ✅ All required fields present")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("INSPECTION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total documents: {total_count}")
        logger.info(f"Valid documents: {total_count - len(poison_docs)}")
        logger.info(f"Poison documents (missing fields): {len(poison_docs)}")

        if missing_fields_counter:
            logger.info("\nMissing field frequency:")
            for field, count in missing_fields_counter.most_common():
                logger.info(f"  - {field}: {count} documents")

        if poison_docs:
            logger.warning("\n⚠️  POISON DOCUMENTS DETECTED:")
            for doc_info in poison_docs:
                logger.warning(
                    f"  - {doc_info['id']}: missing {sorted(doc_info['missing'])}"
                )
            logger.warning("\nThese documents will cause ValidationError during parsing.")
            logger.warning(
                "Enable cleanup-on-failure in SignalRepository to auto-delete."
            )
            sys.exit(1)
        else:
            logger.info("\n✅ All documents are valid. No cleanup required.")
            sys.exit(0)

    except Exception as e:
        logger.critical(f"Inspection failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
