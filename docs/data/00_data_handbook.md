# Data Handbook & Schema Glossary V3.0

This document is the **Definitive Source of Truth** for all data structures in the system. It bridges the gap between the Python domain logic (`schemas.py`), operational storage (Firestore), and analytical storage (BigQuery).

---

## 1. Data Modeling Strategy

We utilize a **Star Schema** variant optimized for BigQuery (Columnar Storage) while maintaining document-oriented consistency in Firestore.

### Dimensional Patterns
1.  **SCD Type 2 (Slowly Changing Dimensions)**: Applied to `dim_strategies`. Configuration changes trigger new versions to preserve historical performance integrity.
2.  **Degenerate Dimensions**: High-cardinality IDs like `signal_id` and `alpaca_order_id` are stored directly in Fact tables.
3.  **Snapshot Grain**: Point-in-time state captured daily for account health (`snapshot_accounts`).

---

## 2. Shared Vocabulary (Enums)

All models share a common set of enums defined in `src/crypto_signals/domain/schemas.py`:
- **AssetClass**: `CRYPTO`, `EQUITY`
- **SignalStatus**: `WAITING`, `INVALIDATED`, `EXPIRED`, `TP1_HIT`, etc.
- **OrderSide**: `buy`, `sell`
- **ExitReason**: `TP1`, `STOP_LOSS`, `COLOR_FLIP`, `MANUAL_EXIT`, etc.

---

## 3. Storage Layers & Entities

### A. Operational Storage (Firestore - "Hot")
Optimized for write speed and real-time lifecycle management.

| Entity | Collection | Description | Key Fields |
| :--- | :--- | :--- | :--- |
| **Strategy** | `dim_strategies` | The "Brain". Defines rules and risk. | `strategy_id`, `active`, `assets`, `risk_params` |
| **Signal** | `live_signals` | Potential opportunities. | `signal_id`, `status`, `valid_until`, `side` |
| **Position** | `live_positions`| Active trades in the broker. | `position_id`, `entry_fill_price`, `current_stop_loss` |

### B. Analytical Warehouse (BigQuery - "Cold")
Optimized for aggregation, backtesting, and performance reporting.

| Entity | Table | Description | Partition Key |
| :--- | :--- | :--- | :--- |
| **Trade Fact** | `fact_trades` | Immutable ledger of closed trades. | `ds` (Execution Date) |
| **Account Snapshot** | `snapshot_accounts` | Daily account health metrics. | `ds` (Snapshot Date) |
| **Rejected Signal** | `fact_rejected_signals`| Shadow tracking for quality gates. | `ds` (Generation Date) |

---

## 4. Detailed Schema Reference

### Account Snapshot (`snapshot_accounts`)
*Daily snapshots captured via `AccountSnapshotPipeline`.*

| Field | Type | Description |
| :--- | :--- | :--- |
| `ds` | `date` | Partition key |
| `account_id` | `str` | Alpaca account ID |
| `equity` | `float` | Total account equity in USD |
| `cash` | `float` | Available cash in USD |
| `buying_power` | `float` | Total Buying Power (Reg T) |
| `drawdown_pct` | `float` | % down from High Water Mark |
| `calmar_ratio` | `float` | Annual Return / Max Drawdown |

### Trade Execution (`fact_trades`)
*Immutable ledger derived from closed `Position` objects.*

| Field | Type | Description |
| :--- | :--- | :--- |
| `ds` | `date` | Execution date |
| `trade_id` | `str` | Unique identifier (signal_id) |
| `strategy_id` | `str` | Originating strategy |
| `symbol` | `str` | Traded asset |
| `side` | `str` | `buy` or `sell` |
| `qty` | `float` | Traded quantity |
| `entry_price` | `float` | Fill price at entry |
| `exit_price` | `float` | Weighted average fill price at exit |
| `pnl_usd` | `float` | Net P&L in USD (after fees) |
| `fees_usd` | `float` | Total fees paid |
| `actual_fee_usd` | `float` | Reconciled fees (T+1 from Broker) |
| `fee_finalized` | `bool` | True if actual fees are reconciled |
| `slippage_pct` | `float` | `abs(entry_price - target_entry_price) / target_entry_price` |
| `trade_duration` | `int` | Duration in seconds |
| `max_favorable_excursion` | `float` | Best price reached during trade |

### Live Signal (`live_signals`)
*Ephemeral opportunities identified by the engine.*

| Field | Type | Description |
| :--- | :--- | :--- |
| `signal_id` | `str` | Deterministic UUID (`ds|strat|sym`) |
| `status` | `str` | Current lifecycle state |
| `valid_until` | `datetime` | Logical expiration (24h/120h) |
| `entry_price` | `float` | Target limit price |
| `take_profit_1` | `float` | First calculated profit target |
| `take_profit_2` | `float` | Second calculated profit target |
| `take_profit_3` | `float` | Third calculated profit target |
| `pattern_name` | `str` | e.g., "Bullish Engulfing" |
| `trade_type` | `str` | `EXECUTED`, `FILTERED`, `THEORETICAL` |

---

## 5. Metric Glossary

| Metric | Level | Formula / Definition |
| :--- | :--- | :--- |
| **Win Rate** | Strategy | `Winning Trades / Total Trades` |
| **Profit Factor** | Strategy | `Gross Profit / Gross Loss` |
| **Sharpe Ratio** | Strategy | `(Return - RiskFree) / StdDev(Return)` |
| **Slippage** | Trade | `(Fill Price - Signal Price) / Signal Price` |
| **Drawdown** | Account | `(Peak - Current) / Peak` |

---

> [!TIP]
> This document is partially maintained by automated sync scripts (Issue #240). Manual edits to the Schema Tables may be overwritten by the CI/CD pipeline.
