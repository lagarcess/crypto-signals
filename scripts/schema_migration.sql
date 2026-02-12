-- Migration Script for Issue 116 (Expanded Account Snapshot)
-- To be run via scripts/run_migration.py (handles substitutions)

-- 1. Apply Schema Changes to Fact Table (Critical Data)
-- We use IF NOT EXISTS to make this idempotent.

-- Ensure snapshot_accounts exists with core schema
CREATE TABLE IF NOT EXISTS `{{PROJECT_ID}}.crypto_analytics.snapshot_accounts` (
    ds DATE,
    account_id STRING,
    equity FLOAT64,
    cash FLOAT64,
    calmar_ratio FLOAT64,
    drawdown_pct FLOAT64
)
PARTITION BY ds;

ALTER TABLE `{{PROJECT_ID}}.crypto_analytics.snapshot_accounts`
ADD COLUMN IF NOT EXISTS buying_power FLOAT64,
ADD COLUMN IF NOT EXISTS regt_buying_power FLOAT64,
ADD COLUMN IF NOT EXISTS daytrading_buying_power FLOAT64,
ADD COLUMN IF NOT EXISTS crypto_buying_power FLOAT64,
ADD COLUMN IF NOT EXISTS initial_margin FLOAT64,
ADD COLUMN IF NOT EXISTS maintenance_margin FLOAT64,
ADD COLUMN IF NOT EXISTS last_equity FLOAT64,
ADD COLUMN IF NOT EXISTS long_market_value FLOAT64,
ADD COLUMN IF NOT EXISTS short_market_value FLOAT64,
ADD COLUMN IF NOT EXISTS currency STRING,
ADD COLUMN IF NOT EXISTS status STRING,
ADD COLUMN IF NOT EXISTS pattern_day_trader BOOL,
ADD COLUMN IF NOT EXISTS daytrade_count INT64,
ADD COLUMN IF NOT EXISTS account_blocked BOOL,
ADD COLUMN IF NOT EXISTS trade_suspended_by_user BOOL,
ADD COLUMN IF NOT EXISTS trading_blocked BOOL,
ADD COLUMN IF NOT EXISTS transfers_blocked BOOL,
ADD COLUMN IF NOT EXISTS multiplier FLOAT64,
ADD COLUMN IF NOT EXISTS sma FLOAT64;

-- 2. Reset Staging Table (Transient Data)
-- Dropping and recreating LIKE the fact table guarantees strictly identical schemas.
-- This prevents any "missing column" errors during insert_rows_json.
DROP TABLE IF EXISTS `{{PROJECT_ID}}.crypto_analytics.stg_accounts_import`;

CREATE TABLE `{{PROJECT_ID}}.crypto_analytics.stg_accounts_import`
LIKE `{{PROJECT_ID}}.crypto_analytics.snapshot_accounts`;

-- 3. Add exit_order_id to fact_trades (Exit Order Tracking)
-- Links BigQuery trade records back to Alpaca exit orders for reconciliation

-- Ensure fact_trades exists with core schema
CREATE TABLE IF NOT EXISTS `{{PROJECT_ID}}.crypto_analytics.fact_trades` (
    ds DATE,
    trade_id STRING,
    account_id STRING,
    strategy_id STRING,
    asset_class STRING,
    symbol STRING,
    side STRING,
    qty FLOAT64,
    entry_price FLOAT64,
    exit_price FLOAT64,
    entry_time TIMESTAMP,
    exit_time TIMESTAMP,
    exit_reason STRING,
    max_favorable_excursion FLOAT64,
    pnl_pct FLOAT64,
    pnl_usd FLOAT64,
    fees_usd FLOAT64,
    slippage_pct FLOAT64,
    trade_duration INT64,
    discord_thread_id STRING,
    trailing_stop_final FLOAT64,
    target_entry_price FLOAT64,
    alpaca_order_id STRING
)
PARTITION BY ds;

ALTER TABLE `{{PROJECT_ID}}.crypto_analytics.fact_trades`
ADD COLUMN IF NOT EXISTS exit_order_id STRING;

-- 4. Add CFEE Reconciliation Fields (Issue #140)
-- Tracks fee settlement status for T+1 reconciliation with Alpaca Activities API
ALTER TABLE `{{PROJECT_ID}}.crypto_analytics.fact_trades`
ADD COLUMN IF NOT EXISTS fee_finalized BOOL,
ADD COLUMN IF NOT EXISTS actual_fee_usd FLOAT64,
ADD COLUMN IF NOT EXISTS fee_calculation_type STRING,
ADD COLUMN IF NOT EXISTS fee_tier STRING,
ADD COLUMN IF NOT EXISTS entry_order_id STRING,
ADD COLUMN IF NOT EXISTS fee_reconciled_at TIMESTAMP;

-- 5. Add Exit Price Reconciliation Fields (Issue #141)
-- Tracks exit price settlement status (mirrors fee_finalized pattern)
ALTER TABLE `{{PROJECT_ID}}.crypto_analytics.fact_trades`
ADD COLUMN IF NOT EXISTS exit_price_finalized BOOL,
ADD COLUMN IF NOT EXISTS exit_price_reconciled_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS exit_price FLOAT64;

-- 5. Reset Staging Table for TRADES
-- Dropping and recreating LIKE the fact table guarantees identical schemas.
DROP TABLE IF EXISTS `{{PROJECT_ID}}.crypto_analytics.stg_trades_import`;

CREATE TABLE `{{PROJECT_ID}}.crypto_analytics.stg_trades_import`
LIKE `{{PROJECT_ID}}.crypto_analytics.fact_trades`;

-- ==========================================
-- TEST ENVIRONMENT (Schema Mirroring)
-- ==========================================

-- 6. Trades (Test) - Mirror CFEE fields
DROP TABLE IF EXISTS `{{PROJECT_ID}}.crypto_analytics.fact_trades_test`;

CREATE TABLE `{{PROJECT_ID}}.crypto_analytics.fact_trades_test`
LIKE `{{PROJECT_ID}}.crypto_analytics.fact_trades`;

-- Note: Since we recreate LIKE the altered fact_trades, we don't need manual ALTERs here.
-- The test table will inherit all new columns (exit_order_id, exit_price, etc).

DROP TABLE IF EXISTS `{{PROJECT_ID}}.crypto_analytics.stg_trades_import_test`;
CREATE TABLE `{{PROJECT_ID}}.crypto_analytics.stg_trades_import_test`
LIKE `{{PROJECT_ID}}.crypto_analytics.fact_trades_test`;

-- 7. Account Snapshots (Test)
CREATE TABLE IF NOT EXISTS `{{PROJECT_ID}}.crypto_analytics.snapshot_accounts_test`
LIKE `{{PROJECT_ID}}.crypto_analytics.snapshot_accounts`;

DROP TABLE IF EXISTS `{{PROJECT_ID}}.crypto_analytics.stg_accounts_import_test`;
CREATE TABLE `{{PROJECT_ID}}.crypto_analytics.stg_accounts_import_test`
LIKE `{{PROJECT_ID}}.crypto_analytics.snapshot_accounts_test`;

-- 6. Rejected Signals (Test & Prod)
-- Ensure PROD exists (was missing in migration)
CREATE TABLE IF NOT EXISTS `{{PROJECT_ID}}.crypto_analytics.fact_rejected_signals`
(
    ds DATE,
    signal_id STRING,
    rejection_reason STRING,
    theoretical_pnl_usd FLOAT64,
    theoretical_pnl_pct FLOAT64,
    theoretical_fees_usd FLOAT64,
    created_at TIMESTAMP
)
PARTITION BY ds;

DROP TABLE IF EXISTS `{{PROJECT_ID}}.crypto_analytics.stg_rejected_signals`;
CREATE TABLE `{{PROJECT_ID}}.crypto_analytics.stg_rejected_signals`
LIKE `{{PROJECT_ID}}.crypto_analytics.fact_rejected_signals`;

-- Test
CREATE TABLE IF NOT EXISTS `{{PROJECT_ID}}.crypto_analytics.fact_rejected_signals_test`
LIKE `{{PROJECT_ID}}.crypto_analytics.fact_rejected_signals`;

DROP TABLE IF EXISTS `{{PROJECT_ID}}.crypto_analytics.stg_rejected_signals_test`;
CREATE TABLE `{{PROJECT_ID}}.crypto_analytics.stg_rejected_signals_test`
LIKE `{{PROJECT_ID}}.crypto_analytics.fact_rejected_signals_test`;
