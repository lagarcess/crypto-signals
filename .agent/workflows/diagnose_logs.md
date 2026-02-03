# Workflow: Diagnose Logs & Book Balancing

This workflow provides tools for analyzing production logs and reconciling the ledger between the Database and Alpaca.

## Command: `/book_balance`

### Description
Performs a "Book Balancing" audit to identify mismatches between Alpaca (Broker) and Firestore (Database). It detects:
*   **Reverse Orphans**: Positions open in Alpaca but missing in DB.
*   **Zombies**: Positions open in DB but missing in Alpaca.

### Usage
python -m crypto_signals.scripts.diagnostics.book_balancing [OPTIONS]

# Options:
#   --target <ID or SYMBOL> : Inspect specific Position ID or Symbol history.
#   --limit  <INT>          : Number of historical orders to fetch (Default: 100).

# Example: Check for specific "missing" BTC position
python -m crypto_signals.scripts.diagnostics.book_balancing --target BTC/USD --limit 500
```

---

## Command: `/diagnose_logs`

### Description
Analyzes Cloud Run logs for errors.

### Usage
```bash
/diagnose_logs --hours 24
```
