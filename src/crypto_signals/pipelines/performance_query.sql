-- Performance Query: Strategy-level metrics from agg_strategy_daily
-- Used by PerformancePipeline.extract() via Path(__file__).parent / "performance_query.sql"
--
-- Parameters (injected via Python str.format):
--   {source_table_id}:   Fully qualified BQ table ID for agg_strategy_daily
--   {baseline_capital}:  Starting capital for equity curve (validated float, see performance.py)
--
-- NOTE on win_rate aggregation:
--   daily_win_rate in the first CTE is a trade-weighted average across symbols
--   (SUM(win_rate * trade_count) / SUM(trade_count)). The historical_metrics CTE
--   then re-weights by daily_trades (which IS SUM(trade_count)), effectively
--   reconstructing the cumulative win count / total count ratio. This is
--   mathematically equivalent to tracking wins/totals separately but avoids
--   adding extra columns to the source table.

WITH daily_strategy_metrics AS (
    SELECT
        ds,
        strategy_id,
        SUM(total_pnl) as daily_pnl,
        SUM(trade_count) as daily_trades,
        SAFE_DIVIDE(SUM(win_rate * trade_count), SUM(trade_count)) as daily_win_rate
    FROM `{source_table_id}`
    GROUP BY ds, strategy_id
),
historical_metrics AS (
    SELECT
        ds,
        strategy_id,
        daily_pnl,
        daily_trades,
        daily_win_rate,
        SUM(daily_trades) OVER (PARTITION BY strategy_id ORDER BY ds) as total_trades,
        SAFE_DIVIDE(
            SUM(daily_win_rate * daily_trades) OVER (PARTITION BY strategy_id ORDER BY ds),
            SUM(daily_trades) OVER (PARTITION BY strategy_id ORDER BY ds)
        ) as win_rate,
        -- Profit Factor: SUM(Gain) / ABS(SUM(Loss))
        SAFE_DIVIDE(
            SUM(IF(daily_pnl > 0, daily_pnl, 0)) OVER (PARTITION BY strategy_id ORDER BY ds),
            ABS(SUM(IF(daily_pnl < 0, daily_pnl, 0)) OVER (PARTITION BY strategy_id ORDER BY ds))
        ) as profit_factor,
        -- Annualized Sharpe (assuming 365 days for Crypto)
        SAFE_DIVIDE(
            AVG(daily_pnl) OVER (PARTITION BY strategy_id ORDER BY ds),
            STDDEV(daily_pnl) OVER (PARTITION BY strategy_id ORDER BY ds)
        ) * SQRT(365) as sharpe_ratio,
        -- Annualized Sortino
        SAFE_DIVIDE(
            AVG(daily_pnl) OVER (PARTITION BY strategy_id ORDER BY ds),
            STDDEV(IF(daily_pnl < 0, daily_pnl, NULL)) OVER (PARTITION BY strategy_id ORDER BY ds)
        ) * SQRT(365) as sortino_ratio,
        -- Max Drawdown calculation using configured baseline capital
        {baseline_capital} + SUM(daily_pnl) OVER (PARTITION BY strategy_id ORDER BY ds) as equity
    FROM daily_strategy_metrics
),
drawdown_calc AS (
    SELECT
        *,
        MAX(equity) OVER (PARTITION BY strategy_id ORDER BY ds) as peak_equity
    FROM historical_metrics
),
max_drawdown_calc AS (
    SELECT
        *,
        SAFE_DIVIDE(peak_equity - equity, peak_equity) as current_drawdown
    FROM drawdown_calc
),
final_metrics AS (
    SELECT
        ds,
        strategy_id,
        CAST(total_trades AS INT64) as total_trades,
        win_rate,
        IFNULL(profit_factor, 1.0) as profit_factor,
        IFNULL(sharpe_ratio, 0.0) as sharpe_ratio,
        IFNULL(sortino_ratio, 0.0) as sortino_ratio,
        MAX(current_drawdown) OVER (PARTITION BY strategy_id ORDER BY ds) * 100.0 as max_drawdown_pct,
        -- TODO(#315): Alpha/Beta require a benchmark index (e.g., BTC or S&P500)
        -- to compute meaningful values. Currently stubbed to 0.0.
        0.0 as alpha,
        0.0 as beta
    FROM max_drawdown_calc
)
SELECT * FROM final_metrics
WHERE ds = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
