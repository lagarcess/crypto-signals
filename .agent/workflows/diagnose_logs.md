# Workflow: Diagnose Logs & Book Balancing

This workflow provides tools for analyzing production logs and reconciling the ledger between the Database and Alpaca.

## Command: `/book_balance`

### Description
Performs a "Book Balancing" audit to identify mismatches between Alpaca (Broker) and Firestore (Database). It detects:
*   **Reverse Orphans**: Positions open in Alpaca but missing in DB.
*   **Zombies**: Positions open in DB but missing in Alpaca.

### Usage
```bash
# General Usage
python -m crypto_signals.scripts.diagnostics.book_balancing --help

# Audit Specific Symbol (e.g. BTC/USD)
python -m crypto_signals.scripts.diagnostics.book_balancing --target "BTC/USD"

# Audit Specific Symbol with a higher limit for historical orders
python -m crypto_signals.scripts.diagnostics.book_balancing --target "BTC/USD" --limit 500
```

---

## Command: `/diagnose_logs`

### Description
Analyzes Cloud Run logs for errors.

### Usage
```bash
/diagnose_logs --hours 24
```
