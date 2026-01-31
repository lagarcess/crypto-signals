# Data Catalog & Metrics Glossary V2.5 (Exhaustive)

## Overview
 Definitive Source of Truth defined in `src/crypto_signals/domain/schemas.py`.

---

## 1. Hot Storage (Firestore)

### `dim_strategies` (Strategy Entity)
*Status: Implemented (Firestore + BigQuery SCD Type 2) | Relationship: One-to-Many with `live_signals`*
The "Brain" of the system. Now synced to BigQuery via `StrategySyncPipeline` (Issue #195).
*   **`strategy_id`** (PK): Unique ID (e.g., `btc_daily_hammer_v1`).
*   **`active`**: Kill switch (Boolean).
*   **`assets`**: List of tradable symbols.
*   **`risk_params`**: JSON. Rules for position sizing (`stop_loss_pct`, `risk_per_trade`).
*   **`confluence_config`**: JSON. (Issue #198 - In Progress) Filters required for entry (e.g., `{"min_adx": 25, "min_volume_ratio": 1.5}`).
*   **`pattern_overrides`**: JSON. (Issue #198 - In Progress) Specific tweaks per pattern type (e.g., `{"Bullish Engulfing": {"strict_trend": true}}`).
*   **`doc_id`**: Auto-generated document ID.

### `dim_assets` (Asset Universe)
*Status: Planned (Issue #200) | Relationship: Referenced by `dim_strategies`*
Defines the tradable universe and asset-specific constraints.
*   **`symbol`** (PK): e.g., `BTC/USD`, `AAPL`.
*   **`asset_class`**: `CRYPTO` | `EQUITY`.
*   **`exchange`**: `ALPACA` | `COINBASE`.
*   **`status`**: `ACTIVE` | `HALTED` | `DELISTED`.
*   **`fractionable`**: Boolean.
*   **`min_order_size`**: Minimum notion.
*   **`min_trade_increment`**: Smallest price movement.

### `live_signals` (Signal Entity)
*Status: Implemented (Firestore) | Relationship: One-to-One with `live_positions` (if triggered)*
*   **`signal_id`**: Deterministic ID (`uuid5`).
*   **`strategy_id`**: Foreign Key to `dim_strategies`.
*   **`ds`**: Signal generation date (partition key).
*   **`status`**: `WAITING`, `INVALIDATED`, `EXPIRED`, `TP_HIT`.
*   **`symbol`**: Asset.
*   **`side`**: `LONG` | `SHORT`.
*   **`asset_class`**: `CRYPTO` | `EQUITY`.
*   **`created_at`**: Timestamp.
*   **`entry_price`**: Limit price for entry.
*   **`suggested_stop`**: Initial Stop Loss.
*   **`take_profit_1`, `take_profit_2`, `take_profit_3`**: Take Profit targets.
*   **`valid_until`**: Logical expiration (24h).
*   **`delete_at`**: Physical TTL (30 days).
*   **`discord_thread_id`**: For notification threading.
*   **`trade_type`**: `EXECUTED`, `FILTERED`, `THEORETICAL`.
*   **Pattern Metadata**:
    *   `pattern_name`: e.g. "Bullish Engulfing".
    *   `confluence_factors`: List of triggers (e.g. `["RSI_DIV", "VCP"]`).
    *   `pattern_classification`: `STANDARD` or `MACRO`.
    *   `structural_anchors`: List of pivot points [{price, time}].
    *   `harmonic_metadata`: Fibonacci ratios for harmonic patterns.

### `live_positions` (Trade Entity - Active)
*Status: Implemented (Alpaca Sync) | Relationship: Links `live_signals` to Broker*
*   **`position_id`**: Links to `signal_id`.
*   **`account_id`**: Alpaca Account ID.
*   **`symbol`**: Asset.
*   **`ds`**: Entry date.
*   **`status`**: `OPEN`, `CLOSED`.
*   **`side`**: `LONG` | `SHORT`.
*   **`qty`**: Number of contracts/shares.
*   **`entry_fill_price`**: Broker execution price.
*   **`current_stop_loss`**: Trailing stop value.
*   **Order Management**:
    *   `alpaca_order_id`: Parent Bracket Order ID.
    *   `tp_order_id`, `sl_order_id`: Child leg IDs.
    *   `exit_order_id`: ID of the closing order.
    *   `failed_reason`: Broker rejection message.
    *   `commission`: Total fees reported.
*   **Lifecycle Timestamps**:
    *   `filled_at`: Entry time.
    *   `exit_time`: Exit time.
*   **Scale-Out Logic**:
    *   `original_qty`: Initial size.
    *   `scaled_out_qty`: Qty closed at TP1.
    *   `scaled_out_price`: Avg price of scale-out.
    *   `breakeven_applied`: Boolean.
*   **Real-time Metrics**:
    *   **`realized_pnl_usd/pct`**: Realized P&L (includes scale-outs).
    *   `entry_slippage_pct`: vs Target Entry.
    *   `exit_slippage_pct`: vs Target Exit.

### `rejected_signals` (Shadow Entity)
*Status: Implemented (Firestore) | Relationship: Orphaned Signal (No Trade)*
*   **`signal_id`**: Links to original detection.
*   **`strategy_id`**: The strategy that generated it.
*   **`rejection_reason`**: `RSI_TOO_HIGH`, `VOLUME_TOO_LOW`, `RISK_TOO_HIGH`, `INSUFFICIENT_BP`.
*   **`theoretical_pnl_usd`**: Simulated P&L if we had taken it.
*   **`theoretical_pnl_pct`**: Simulated Return %.
*   **`theoretical_fees_usd`**: Simulated fees.
*   **`rejection_metadata`**: JSON snapshot of indicators at rejection.

### `job_metadata` (System State)
*Status: Defined in code (Issue #197) | Relationship: Audit Log*
*   **`job_id`**: Cloud Run Execution ID.
*   **`run_date`**: Timestamp.
*   **`git_hash`**: Commit SHA of the code version (Critical for debugging).
*   **`config_snapshot`**: JSON. Dump of critical settings (`TTL`, `Env`) used in run.
*   **`status`**: `SUCCESS` | `FAILURE`.

### `system_checks` (Health Monitoring)
*Status: Implemented (Reconciler) | Relationship: Operational Logs*
*   **`check_id`**: UUID.
*   **`timestamp`**: when check ran.
*   **`zombies`**: List of positions closed in Broker but Open in DB.
*   **`orphans`**: List of positions Open in Broker but Missing in DB.
*   **`reconciled_count`**: Number of fixes applied.

---

## 2. Cold Storage (BigQuery)

### `fact_trades` (Performance Metrics)
*Status: Implemented (Loop A) | Relationship: Derived from `live_positions`*
*   **`trade_id`**
*   **`strategy_id`**
*   **`signal_id`**: Degenerate Dimension.
*   **`side`**: `LONG` | `SHORT`.
*   **`asset_class`**: `CRYPTO` | `EQUITY`.
*   **Financial Metrics**:
    *   `pnl_usd`: Net Profit ($).
    *   `pnl_pct`: Net Return (%).
    *   `fees_usd`: Total Fees.
    *   `actual_fee_usd`: Reconciled Fee from Broker.
    *   `fee_tier`: Maker/Taker.
    *   `fee_reconciled_at`: Timestamp of final fee patch.
    *   **`fee_finalized`**: Boolean (True = Reconciled).
    *   `fee_calculation_type`: `ESTIMATED` | `ACTUAL`.
*   **Execution Metrics**:
    *   **`multiplier`**: Contract multiplier (Currently missing in implementation - Issue #202).
    *   `slippage_pct`: `abs(Fill - Signal) / Signal`.
    *   `trade_duration`: Seconds open.
    *   `entry_time`, `exit_time`.
    *   **`exit_price`**: Final weighted avg exit price.
    *   `max_favorable_excursion`: Highest price reached.
    *   `discord_thread_id`: Context link.
    *   `alpaca_order_id`: Audit link.

### `agg_strategy_daily` (Periodic Aggregate)
*Status: Planned (Issue #201) | Grain: 1 Row per Strategy per Day*
*   **`strategy_id`**
*   **`date`**
*   **`total_trades`**: Count.
*   **`win_rate`**: Daily Win Rate.
*   **`profit_factor`**: Daily PF.
*   **`net_pnl_usd`**: Sum PnL.
*   **`net_pnl_pct`**: Sum Return.
*   **`max_drawdown_daily`**: Worst intraday drop.

### `snapshot_accounts` (Account Health Metrics)
*Status: Implemented (Loop D, Issue #196 ✅) | Relationship: Periodic Snapshot of Account State*
Daily snapshots captured via `AccountSnapshotPipeline`.
*   **`account_id`**
*   **`snapshot_time`**
*   **Equity Metrics**:
    *   `equity`: Net Liquidation Value.
    *   `cash`: Unsettled + Settled Cash.
    *   `last_equity`: Previous day close.
    *   `long_market_value`, `short_market_value`.
    *   `multiplier`: Account-level leverage multiplier.
*   **Risk Metrics**:
    *   `buying_power`: Total BP (Reg T).
    *   `regt_buying_power`: Reg T BP.
    *   `daytrading_buying_power`: DT BP.
    *   `crypto_buying_power`: Crypto-specific BP.
    *   `initial_margin`, `maintenance_margin`.
    *   `drawdown_pct`: `%` down from High Water Mark.
    *   `calmar_ratio`: `Annual Return / Max Drawdown`.
*   **Constraint/Status Metrics**:
    *   `status`: `ACTIVE`, `ACCOUNT_UPDATED`.
    *   `daytrade_count`: Number of DTs (PDT Rule).
    *   `pattern_day_trader`: Boolean Flag.
    *   `account_blocked`: Boolean.
    *   `trade_suspended_by_user`: Boolean.
    *   `transfers_blocked`: Boolean.
    *   `currency`: `USD`.
    *   `sma`: Account-level SMA (if provided by broker).

### `fact_signals_expired` (Noise Metrics)
*   **`signal_id`**
*   **`max_mfe`**: Did it go in our direction anyway?
*   **`distance_to_trigger`**: How close was it?

---

## 3. Metric Glossary (Analytical)

| Level | Metric | Formula/Definition |
| :--- | :--- | :--- |
| **Strategy** | **Win Rate** | `Wins / Total Trades` |
| **Strategy** | **Profit Factor** | `Gross Profit / Gross Loss` |
| **Strategy** | **Sharpe Ratio** | `(Return - RiskFree) / StdDev` |
| **Strategy** | **Sortino Ratio** | `(Return - RiskFree) / DownsideDev` |
| **Strategy** | **Alpha** | `Return - Benchmark Return` |
| **Strategy** | **Beta** | `Covariance(Strategy, Benchmark) / Variance(Benchmark)` |
| **Strategy** | **Total Trades** | Count of closed trades. |
| **Trade** | **Slippage** | `abs(FilledPrice - OrderPrice) / OrderPrice` |
| **Account** | **Drawdown** | `(PeakEquity - CurrentEquity) / PeakEquity` |
| **Account** | **Calmar** | `CAGR / MaxDrawdown` |
