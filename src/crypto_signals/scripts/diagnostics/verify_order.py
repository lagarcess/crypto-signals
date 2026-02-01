import json
from typing import Any, Optional

import typer
from rich import print as rprint
from rich.console import Console

from crypto_signals.config import get_trading_client
from crypto_signals.repository.firestore import PositionRepository

app = typer.Typer(help="Deep Order Verification Tool")
console = Console()


@app.command()
def verify(
    order_id: Optional[str] = typer.Option(
        None, "--order-id", "--id", help="Alpaca Order ID (UUID)"
    ),
    symbol: Optional[str] = typer.Option(
        None, "--symbol", "-s", help="Symbol to check positions for"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """
    Verify order status and cross-check positions between Alpaca and Firestore.
    """
    if not order_id and not symbol:
        typer.echo("Error: Must provide either --order-id or --symbol")
        raise typer.Exit(code=1)

    client = get_trading_client()
    repo = PositionRepository()

    result: dict[str, Any] = {
        "order_status": "unknown",
        "alpaca_order": None,
        "alpaca_position": None,
        "firestore_position": None,
        "discrepancies": [],
    }

    # 1. Check Order
    if order_id:
        try:
            order = client.get_order_by_id(order_id)
            # Serialize order to dict safely
            if hasattr(order, "model_dump"):
                order_data = order.model_dump()
            elif hasattr(order, "dict"):
                order_data = order.dict()
            else:
                order_data = order.__dict__

            result["alpaca_order"] = order_data
            result["order_status"] = "found"

            # If symbol not provided, try to infer from order
            if not symbol:
                # Alpaca Order objects usually have 'symbol' attribute
                # Accessing via dictionary if it's already converted, or attribute
                if isinstance(order_data, dict):
                    symbol = order_data.get("symbol")
                elif hasattr(order, "symbol"):
                    symbol = order.symbol

        except Exception:
            result["order_status"] = "not_found"
            # Only record error if it's NOT a 404 (which is expected if ID is wrong)
            # But here we assume ID provided SHOULD exist or we want to verify it doesn't.
            # So "not_found" is a valid status.
            # If it's a connection error, that's different.
            # We assume 404 means "definitely not on Alpaca".
            pass

    # 2. Check Positions
    if symbol:
        # Alpaca Position
        try:
            pos = client.get_open_position(symbol)
            if hasattr(pos, "model_dump"):
                pos_data = pos.model_dump()
            elif hasattr(pos, "dict"):
                pos_data = pos.dict()
            else:
                pos_data = pos.__dict__
            result["alpaca_position"] = pos_data
        except Exception:
            # Not found is expected if closed
            pass

        # Firestore Position
        open_positions = repo.get_open_positions()
        fs_pos = next((p for p in open_positions if p.symbol == symbol), None)

        if fs_pos:
            result["firestore_position"] = fs_pos.model_dump(mode="json")

        # 3. Cross Check
        alpaca_exists = result["alpaca_position"] is not None
        firestore_exists = result["firestore_position"] is not None

        if alpaca_exists and not firestore_exists:
            result["discrepancies"].append("Position in Alpaca but not in Firestore")
        elif not alpaca_exists and firestore_exists:
            result["discrepancies"].append("Position in Firestore but not in Alpaca")
        elif alpaca_exists and firestore_exists:
            # Basic quantity check
            # Handle different ways qty might be stored (str vs float)
            a_qty = float(result["alpaca_position"].get("qty", 0))
            f_qty = float(result["firestore_position"].get("qty", 0))

            # Use a small epsilon for float comparison
            if abs(a_qty - f_qty) > 0.0001:
                result["discrepancies"].append(
                    f"Quantity Mismatch: Alpaca={a_qty}, Firestore={f_qty}"
                )

    # Output
    if json_output:
        typer.echo(json.dumps(result, default=str, indent=2))
    else:
        print_human_report(result, order_id, symbol)


def print_human_report(
    result: dict[str, Any], order_id: Optional[str], symbol: Optional[str]
):
    """Print a human-readable report using Rich."""
    rprint("[bold blue]Deep Order Verification[/bold blue]")
    if order_id:
        rprint(f"Checking Order ID: [yellow]{order_id}[/yellow]")
    if symbol:
        rprint(f"Checking Symbol: [yellow]{symbol}[/yellow]")

    rprint("\n[bold]1. Alpaca Order Status[/bold]")
    if result["order_status"] == "found":
        order = result["alpaca_order"] or {}
        rprint(f"  Status: [green]{order.get('status')}[/green]")
        rprint(f"  Symbol: {order.get('symbol')}")
        rprint(f"  Side: {order.get('side')}")
        rprint(f"  Qty: {order.get('qty')}")
        # Handle filled_qty / filled_avg_price safely
        filled_qty = order.get("filled_qty")
        filled_avg_price = order.get("filled_avg_price")
        if filled_qty is not None:
            rprint(f"  Filled: {filled_qty} @ {filled_avg_price}")
    else:
        rprint("  Status: [red]Order not found (404)[/red]")

    if symbol:
        rprint(f"\n[bold]2. Position Status ({symbol})[/bold]")

        # Alpaca
        a_pos = result["alpaca_position"]
        a_status = "[green]FOUND[/green]" if a_pos else "[red]NOT FOUND[/red]"
        rprint(f"  Alpaca: {a_status}")
        if a_pos:
            rprint(f"    Qty: {a_pos.get('qty')}")
            rprint(f"    Entry: {a_pos.get('avg_entry_price')}")
            rprint(f"    P&L: {a_pos.get('unrealized_pl')}")

        # Firestore
        f_pos = result["firestore_position"]
        f_status = "[green]FOUND[/green]" if f_pos else "[red]NOT FOUND[/red]"
        rprint(f"  Firestore: {f_status}")
        if f_pos:
            rprint(f"    Qty: {f_pos.get('qty')}")
            rprint(f"    Status: {f_pos.get('status')}")
            rprint(f"    ID: {f_pos.get('position_id')}")

    rprint("\n[bold]3. Discrepancies[/bold]")
    if result["discrepancies"]:
        rprint("[bold red]DISCREPANCY DETECTED:[/bold red]")
        for d in result["discrepancies"]:
            rprint(f"  - {d}")
    else:
        if symbol:
            rprint("[green]MATCH: No discrepancies found[/green]")
        else:
            rprint("[dim]No position check requested[/dim]")


if __name__ == "__main__":
    app()
