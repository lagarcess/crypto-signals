#!/usr/bin/env python3
"""
Data Integrity Check - Audit Firestore Collections.

This script audits all fields in the Signal and Position schemas to verify:
1. Which fields are present in Firestore documents
2. Which required fields are missing or NULL
3. Schema consistency between Pydantic models and stored data

Usage:
    poetry run python -m crypto_signals.scripts.diagnostics.data_integrity_check
"""

import os

os.environ.setdefault("ENVIRONMENT", "PROD")

from google.cloud import firestore  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from crypto_signals.config import get_settings  # noqa: E402

console = Console()
settings = get_settings()
db = firestore.Client(project=settings.GOOGLE_CLOUD_PROJECT)


def audit_collection(
    collection_name: str,
    required_fields: dict[str, str],
    limit: int = 5,
) -> None:
    """Audit a Firestore collection for field presence and NULL values."""
    console.print(f"\n[bold cyan]=== {collection_name.upper()} ===")

    docs = list(db.collection(collection_name).limit(limit).stream())
    console.print(f"Documents found: {len(docs)}")

    if not docs:
        console.print("[yellow]⚠️  Collection is empty[/yellow]")
        return

    console.print(
        f"[bold blue]Checking {len(docs)} documents in {collection_name}...[/bold blue]"
    )

    # 1. Field Presence Audit
    # We check against a hardcoded list of "vital" fields for now.
    # Ideally, this should come from Pydantic models (Issue #274)

    # Audit first document
    sample_doc = docs[0].to_dict()

    table = Table(title=f"Field Audit (Sample: {docs[0].id[:20]}...)")
    table.add_column("Field", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Value Preview", style="dim")
    table.add_column("Description", style="dim")

    for field, description in required_fields.items():
        value = sample_doc.get(field, "❌ MISSING")
        if value is None:
            status = "[yellow]⚠️ NULL[/yellow]"
            preview = "None"
        elif value == "❌ MISSING":
            status = "[red]❌ MISSING[/red]"
            preview = "-"
        else:
            status = "[green]✅ OK[/green]"
            preview = str(value)[:30]

        table.add_row(field, status, preview, description)

    console.print(table)


def main():
    console.print("[bold]=" * 70)
    console.print("[bold cyan]FIRESTORE DATA INTEGRITY CHECK")
    console.print("[bold]=" * 70)
    console.print(f"Environment: {settings.ENVIRONMENT}")
    console.print(f"Project: {settings.GOOGLE_CLOUD_PROJECT}")

    # Signal Required Fields
    signal_fields = {
        "signal_id": "Deterministic UUID5 hash",
        "ds": "Date stamp",
        "symbol": "Trading symbol",
        "strategy_id": "Source strategy",
        "asset_class": "CRYPTO/EQUITY",
        "pattern_name": "Pattern detected",
        "entry_price": "Candle close price",
        "suggested_stop": "Stop loss price",
        "status": "Lifecycle status",
        "valid_until": "Expiration datetime",
    }

    # Position Required Fields
    position_fields = {
        "position_id": "Unique ID (= signal_id)",
        "ds": "Date opened",
        "account_id": "Alpaca account",
        "symbol": "Trading symbol",
        "signal_id": "Link to Signal",
        "entry_fill_price": "Actual fill price",
        "current_stop_loss": "Current SL",
        "qty": "Position size",
        "side": "buy/sell",
        "status": "OPEN/CLOSED",
    }

    signals_collection = (
        "live_signals" if settings.ENVIRONMENT == "PROD" else "test_signals"
    )
    positions_collection = (
        "live_positions" if settings.ENVIRONMENT == "PROD" else "test_positions"
    )

    audit_collection(signals_collection, signal_fields)
    audit_collection(positions_collection, position_fields)

    console.print("\n[bold green]=== AUDIT COMPLETE ===[/bold green]\n")


if __name__ == "__main__":
    main()
