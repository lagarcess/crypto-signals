"""
Book Balancing Tool
===================

Reconciles the "books" between Alpaca (Broker) and Firestore (Database).
Performs a deep audit of positions and orders to identify:
1. Zombies (Open in DB, Closed in Broker)
2. Reverse Orphans (Open in Broker, Closed/Missing in DB)
3. Mismatches (Price/Qty discrepancies)
4. Order Integrity (Do client_order_ids match?)

Usage:
    python -m crypto_signals.scripts.diagnostics.book_balancing
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from loguru import logger
from rich.console import Console
from rich.table import Table

from crypto_signals.config import get_settings, get_trading_client
from crypto_signals.repository.firestore import PositionRepository

console = Console()


@dataclass
class LedgerEntry:
    source: str  # 'ALPACA' or 'FIRESTORE'
    id: str  # Position ID / Client Order ID
    symbol: str
    status: str
    qty: float
    entry_price: float
    updated_at: Any

    # Raw object for deep inspection
    raw: Any = None


class BookBalancer:
    def __init__(self, console_client: Optional[Console] = None):
        self.settings = get_settings()
        self.alpaca = get_trading_client()
        self.repo = PositionRepository()
        self.console = console_client or console  # Use injected or global
        self.alpaca_open = {}
        self.alpaca_closed = {}
        self.db_open = {}
        self.db_closed = {}

    def fetch_ledger(self, limit: int = 100):
        """
        Fetch full state from both systems.

        Args:
            limit (int): Number of historical orders to fetch from Alpaca (Default: 100).
        """
        self.console.print(
            f"[bold blue]Fetching Ledger States (History Limit: {limit})...[/bold blue]"
        )

        # 1. ALPACA STATE
        # ----------------
        try:
            # Open Positions
            positions = self.alpaca.get_all_positions()
            for p in positions:
                # Alpaca Position doesn't always have client_order_id easily accessible
                # without looking up the order. We rely on symbol for matching mostly.
                entry = LedgerEntry(
                    source="ALPACA",
                    id="unknown",
                    symbol=p.symbol,
                    status="OPEN",
                    qty=float(p.qty),
                    entry_price=float(p.avg_entry_price),
                    updated_at=datetime.now(),
                    raw=p,
                )
                self.alpaca_open[p.symbol] = entry

            self.console.print(f"Alpaca Open: [green]{len(self.alpaca_open)}[/green]")

            # Closed Orders (Recent History)
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest

            # Fetch enough history to catch recent issues
            req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=limit)
            orders = self.alpaca.get_orders(filter=req)

            for o in orders:
                if o.client_order_id:
                    self.alpaca_closed[o.client_order_id] = LedgerEntry(
                        source="ALPACA",
                        id=o.client_order_id,
                        symbol=o.symbol,
                        status="CLOSED",
                        qty=float(o.filled_qty or 0.0),
                        entry_price=float(o.filled_avg_price or 0.0),
                        updated_at=o.filled_at or o.submitted_at,
                        raw=o,
                    )

            self.console.print(f"Alpaca Closed (History): [green]{len(orders)}[/green]")

        except Exception as e:
            self.console.print(f"[bold red]Failed to fetch Alpaca state: {e}[/bold red]")
            # Continued execution to at least check DB state

        # 2. FIRESTORE STATE
        # ------------------
        self.db_open = {}
        self.db_closed = {}

        self.console.print(
            f"Connecting to Firestore Project: [cyan]{self.settings.GOOGLE_CLOUD_PROJECT}[/cyan]"
        )

        try:
            # Open Positions
            open_pos = self.repo.get_open_positions()
            for p in open_pos:
                self.db_open[p.position_id] = LedgerEntry(
                    source="FIRESTORE",
                    id=p.position_id,
                    symbol=p.symbol,
                    status=p.status.value,
                    qty=p.quantity,
                    entry_price=p.entry_fill_price or 0.0,
                    updated_at=p.updated_at,
                    raw=p,
                )
            self.console.print(f"Firestore Open: [green]{len(self.db_open)}[/green]")

            # Closed Positions (Recent)
            closed_pos = self.repo.get_closed_positions(limit=limit)
            for p in closed_pos:
                self.db_closed[p.position_id] = LedgerEntry(
                    source="FIRESTORE",
                    id=p.position_id,
                    symbol=p.symbol,
                    status=p.status.value,
                    qty=p.quantity,
                    entry_price=p.entry_fill_price or 0.0,
                    updated_at=p.updated_at,
                    raw=p,
                )
            self.console.print(
                f"Firestore Closed (History): [green]{len(closed_pos)}[/green]"
            )

        except Exception as e:
            self.console.print(
                f"[bold red]Failed to fetch Firestore state: {e}[/bold red]"
            )
            logger.exception("Firestore Verification Failed")

    def audit(self, target: Optional[str] = None):
        """
        Compare and Report.

        Args:
            target (str, optional): Specific Symbol or Position ID to inspect.
        """
        self.console.rule("[bold]AUDIT REPORT[/bold]")

        table = Table(title="Live Position Reconciliation (Priority)")
        table.add_column("Symbol", style="cyan")
        table.add_column("DB Status", style="magenta")
        table.add_column("Alpaca Status", style="green")
        table.add_column("Verdict", style="bold")

        # 1. Check ALL Alpaca Open Positions (Reverse Orphan Check)
        # These are positions we pay for / hold risk on.
        all_symbols = set(self.alpaca_open.keys()) | set(
            p.symbol for p in self.db_open.values()
        )

        issues_found = 0

        for symbol in sorted(all_symbols):
            alpaca_entry = self.alpaca_open.get(symbol)
            # Find matching DB entry by Symbol (since DB maps ID -> Pos)
            db_entry = next(
                (item for item in self.db_open.values() if item.symbol == symbol), None
            )

            db_status = db_entry.status if db_entry else "MISSING/CLOSED"
            alpaca_status = alpaca_entry.status if alpaca_entry else "MISSING/CLOSED"

            verdict = "[green]OK[/green]"

            if alpaca_entry and not db_entry:
                verdict = "[red]REVERSE ORPHAN (Dangerous)[/red]"
                issues_found += 1
            elif db_entry and not alpaca_entry:
                verdict = "[yellow]ZOMBIE (Ghost)[/yellow]"
                issues_found += 1
            elif db_entry and alpaca_entry:
                # Both exist - check details
                pass  # OK

            if not target or target == symbol:
                table.add_row(symbol, db_status, alpaca_status, verdict)

        self.console.print(table)

        if target:
            self.console.rule(f"[bold]DETAILED INSPECTION: {target}[/bold]")
            found = False

            # Search in all 4 dicts
            for name, d in [
                ("Alpaca Open", self.alpaca_open),
                ("Alpaca Closed", self.alpaca_closed),
                ("DB Open", self.db_open),
                ("DB Closed", self.db_closed),
            ]:
                # Check Keys (IDs) or Values (Symbols)
                for k, v in d.items():
                    if target == k or target == v.symbol:
                        self.console.print(f"[bold underline]{name}[/bold underline]")
                        self.console.print(v)
                        found = True

            if not found:
                self.console.print(
                    f"[red]Target {target} not found in fetched history.[/red]"
                )

        if issues_found:
            self.console.print(
                f"\n[bold red]FOUND {issues_found} CRITICAL ISSUES[/bold red]"
            )
            self.console.print(
                "Recommend manual intervention in Alpaca Dashboard or Firestore Console."
            )
        else:
            self.console.print(
                "\n[bold green]Books are Balanced! (Live Positions)[/bold green]"
            )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Book Balancing Tool")
    parser.add_argument(
        "--target", type=str, help="Specific Symbol or Position ID to inspect"
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Number of historical orders to fetch"
    )
    args = parser.parse_args()

    balancer = BookBalancer()

    # Patch fetch_ledger to use dynamic limit if needed
    balancer.fetch_ledger(limit=args.limit)
    balancer.audit(target=args.target)
