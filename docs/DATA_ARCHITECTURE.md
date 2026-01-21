# Data Architecture & Schemas

**Current State: January 2026**

This document outlines the high-level data flow and storage schema for Crypto Sentinel.

> **Visual Schema**: A DBML file is available at `docs/current_schema.dbml` for generating visual diagrams.

## Architecture Overview

1.  **Hot Storage (Firestore)**: Operational database for real-time signaling and trade management.
2.  **Cold Storage (BigQuery)**: Analytical warehouse for backtesting, performance metrics, and account snapshots.
3.  **Pipelines**: Python-based ETL jobs that move data from Hot to Cold storage daily.

---

## 1. Hot Storage (Firestore)

**Project**: `{{PROJECT_ID}}`
**Role**: Operational State & Configuration

| Collection | Description | Key Fields |
| :--- | :--- | :--- |
| **dim_strategies** | Configuration for trading strategies. | `strategy_id`, `active`, `timeframe`, `assets`, `risk_params` |
| **live_signals** | Ephemeral trading opportunities detected by engine. | `signal_id`, `status`, `symbol`, `pattern_name`, `expiration_at` |
| **live_positions** | Active trades managed by the bot. | `position_id`, `status` (OPEN/CLOSED), `entry_fill_price`, `current_stop` |

---

## 2. BigQuery Analytics

**Dataset**: `{{PROJECT_ID}}.crypto_analytics`
**Role**: Historical Analysis & Performance Reporting

### Core Tables

| Table Name | Type | Description | Key Columns |
| :--- | :--- | :--- | :--- |
| **fact_trades** | FACT | Immutable ledger of all completed trades. | `trade_id`, `pnl_usd`, `pnl_pct`, `slippage_pct`, `max_favorable_excursion` |
| **snapshot_accounts** | SNAPSHOT | Daily snapshot of account equity and risk metrics. | `account_id`, `equity`, `cash`, `buying_power`, `calmar_ratio`, `drawdown_pct` |
| **summary_strategy_performance** | AGGREGATE | Daily performance stats per strategy. | `strategy_id`, `win_rate`, `sharpe_ratio`, `profit_factor`, `alpha`, `beta` |

### Environment Isolation

We support isolated environments to prevent test data from polluting production analytics.

| Environment | Firestore Collection | BigQuery Table Suffix |
| :--- | :--- | :--- |
| **PROD** | `live_positions` | (None) e.g., `fact_trades` |
| **DEV / TEST** | `test_positions` | `_test` e.g., `fact_trades_test` |

> **Note**: Pipeline logic automatically routes to the correct table based on the `ENVIRONMENT` setting.

---

## 3. Data Flow

1.  **Trade Archival Pipeline**:
    *   **Source**: `live_positions` (Firestore) where `status = CLOSED`.
    *   **Enrich**: Alpaca API (Exact Fill Times, Fees).
    *   **Target**: `fact_trades` (BigQuery).

2.  **Account Snapshot Pipeline**:
    *   **Source**: Alpaca API (Account State, Portfolio History).
    *   **Target**: `snapshot_accounts` (BigQuery).

3.  **Strategy Performance** (Planned):
    *   **Source**: `fact_trades`.
    *   **Target**: `summary_strategy_performance`.
