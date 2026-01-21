## Problem
Issue #118: "Theoretical Slippage - Inject synthetic slippage for honest P&L comparison".
Currently, theoretical trades (simulated execution in non-production environments) are not tracked as formal `Position` objects. They are skipped or logged but not persisted, preventing accurate P&L analysis and slippage tracking against live data.

## Solution
Implemented a dedicated `_execute_theoretical_order` path in `ExecutionEngine`.
- **Synthetic Slippage**: Injects positive (buy) or negative (sell) slippage based on `THEORETICAL_SLIPPAGE_PCT` configuration.
- **Position Creation**: Creates a `Position` object with `trade_type="THEORETICAL"`, effectively simulating a filled order.
- **Reconciliation**: Updated `StateReconciler` to filter out these theoretical positions to prevent them from being flagged as "zombies" (since they don't exist in the broker account).

## Changes
- **`src/crypto_signals/config.py`**: Added `THEORETICAL_SLIPPAGE_PCT` setting.
- **`src/crypto_signals/engine/execution.py`**:
    - Added `_execute_theoretical_order` method.
    - Updated `execute_signal` to route to theoretical execution when appropriate.
    - Removed legacy paper trading safety check (redundant with new gating logic).
    - Updated `modify_stop_loss`, `scale_out_position` to handle theoretical trades in-memory.
- **`src/crypto_signals/engine/reconciler.py`**: Updated `reconcile()` to ignore `THEORETICAL` positions.
- **Tests**:
    - Created `tests/engine/test_theoretical_execution.py`.
    - Created `tests/engine/test_reconciler_theoretical.py`.
    - Updated `tests/engine/test_execution.py` and `tests/engine/test_reconciler.py` to align with new logic.

## Verification
- [x] Unit Tests passed (`poetry run pytest`)
- [x] System checks passed (`ruff`, `mypy`)
- [x] Manual verification (covered by new integration tests)
