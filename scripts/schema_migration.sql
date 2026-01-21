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
