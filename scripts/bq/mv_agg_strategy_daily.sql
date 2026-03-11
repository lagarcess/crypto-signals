-- Materialized View: agg_strategy_daily
-- Replaces: src/crypto_signals/pipelines/agg_strategy_daily.py
-- Issue: #367
--
-- This view aggregates fact_trades by (ds, strategy_id, symbol) to produce
-- daily strategy performance metrics. Refreshes every 24 hours automatically.
--
-- NOTE: BigQuery Materialized Views have restrictions:
--   - Must reference a single base table
--   - Cannot use CONCAT in MV definition; agg_id computed in SELECT
--   - Incremental refresh only works with aggregate functions

CREATE MATERIALIZED VIEW IF NOT EXISTS `{project_id}.crypto_analytics.agg_strategy_daily`
OPTIONS (
    enable_refresh = true,
    refresh_interval_minutes = 1440,
    description = 'Daily strategy aggregation over fact_trades. Auto-refreshed every 24h. Replaces agg_strategy_daily.py (Issue #367).'
)
AS
SELECT
    ds,
    CONCAT(CAST(ds AS STRING), '|', strategy_id, '|', symbol) AS agg_id,
    strategy_id,
    symbol,
    SUM(pnl_usd) AS total_pnl,
    SAFE_DIVIDE(COUNTIF(pnl_usd > 0), COUNT(*)) AS win_rate,
    COUNT(*) AS trade_count
FROM `{project_id}.crypto_analytics.fact_trades`
GROUP BY ds, strategy_id, symbol;
