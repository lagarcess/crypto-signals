import os

# FORCE PROD for this script
os.environ["ENVIRONMENT"] = "PROD"

from google.cloud import firestore  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.prompt import Confirm  # noqa: E402

from crypto_signals.config import get_settings  # noqa: E402

console = Console()
settings = get_settings()
db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)


def main():
    collection_name = "live_positions"
    console.print(
        f"[bold red]=== FORCE PURGE {collection_name.upper()} (PROD) ===[/bold red]"
    )

    # 1. List positions
    docs = list(db.collection(collection_name).stream())
    count = len(docs)

    console.print(f"Found {count} positions in {collection_name}.")

    if count == 0:
        return

    # 2. Confirm
    if not Confirm.ask(
        f"DANGER: Are you sure you want to PERMANENTLY DELETE all {count} PROD positions?"
    ):
        return
    console.print("Auto-confirming purge...")

    # 3. Delete
    batch = db.batch()
    deleted = 0
    for i, doc in enumerate(docs):
        batch.delete(doc.reference)
        deleted += 1
        if (i + 1) % 400 == 0:
            batch.commit()
            batch = db.batch()
            console.print(f"Deleted {deleted}/{count}...")

    if deleted % 400 != 0:
        batch.commit()

    console.print(f"[green]Successfully deleted {deleted} positions.[/green]")


if __name__ == "__main__":
    main()
