-- Migration Script for Issue 116 (Expanded Account Snapshot)
-- To be run via scripts/run_migration.py (handles substitutions)

-- 1. Apply Schema Changes to Fact Table (Critical Data)
-- We use IF NOT EXISTS to make this idempotent.
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
ADD COLUMN IF NOT EXISTS exit_price_reconciled_at TIMESTAMP;

-- 5. Reset Staging Table for TRADES
-- Dropping and recreating LIKE the fact table guarantees identical schemas.
DROP TABLE IF EXISTS `{{PROJECT_ID}}.crypto_analytics.stg_trades_import`;

CREATE TABLE `{{PROJECT_ID}}.crypto_analytics.stg_trades_import`
LIKE `{{PROJECT_ID}}.crypto_analytics.fact_trades`;

-- ==========================================
-- TEST ENVIRONMENT (Schema Mirroring)
-- ==========================================

-- 6. Trades (Test) - Mirror CFEE fields
CREATE TABLE IF NOT EXISTS `{{PROJECT_ID}}.crypto_analytics.fact_trades_test`
LIKE `{{PROJECT_ID}}.crypto_analytics.fact_trades`;

-- Ensure CFEE fields exist in test table
ALTER TABLE `{{PROJECT_ID}}.crypto_analytics.fact_trades_test`
ADD COLUMN IF NOT EXISTS fee_finalized BOOL,
ADD COLUMN IF NOT EXISTS actual_fee_usd FLOAT64,
ADD COLUMN IF NOT EXISTS fee_calculation_type STRING,
ADD COLUMN IF NOT EXISTS fee_tier STRING,
ADD COLUMN IF NOT EXISTS entry_order_id STRING,
ADD COLUMN IF NOT EXISTS fee_reconciled_at TIMESTAMP;

-- Ensure Exit Price fields exist in test table (Issue #141)
ALTER TABLE `{{PROJECT_ID}}.crypto_analytics.fact_trades_test`
ADD COLUMN IF NOT EXISTS exit_price_finalized BOOL,
ADD COLUMN IF NOT EXISTS exit_price_reconciled_at TIMESTAMP;

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
