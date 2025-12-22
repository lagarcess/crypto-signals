"""
Data Schemas for Crypto Sentinel.

This module defines the strict "Data Contract" between Python logic,
Firestore (NoSQL), and BigQuery (SQL). All models use Pydantic for
validation and serialization.

Architecture Overview (9 Tables):
- Firestore Configuration: dim_strategies (1 table)
- Firestore Operational: live_signals, live_positions (2 tables)
- BigQuery Staging: stg_trades_import, stg_accounts_import,
  stg_performance_import (3 tables)
- BigQuery Analytics: fact_trades, snapshot_accounts,
  summary_strategy_performance (3 tables)
"""

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# =============================================================================
# CONSTANTS
# =============================================================================

# Fixed namespace for deterministic UUID generation (uuid5)
# Using DNS namespace as a stable, well-known base
NAMESPACE_SENTINEL = uuid.NAMESPACE_DNS


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_deterministic_id(key: str) -> str:
    """
    Generate a deterministic UUID5 from a key string.

    Uses a fixed namespace to ensure the same key always produces
    the same UUID across all executions.

    Args:
        key: A unique string to hash (e.g., "2024-01-15|momentum|BTC/USD")

    Returns:
        str: A deterministic UUID string

    Example:
        >>> get_deterministic_id("2024-01-15|momentum|BTC/USD")
        'a1b2c3d4-e5f6-5a7b-8c9d-0e1f2a3b4c5d'
    """
    return str(uuid.uuid5(NAMESPACE_SENTINEL, key))


# =============================================================================
# ENUMS (The Vocabulary)
# =============================================================================


class AssetClass(str, Enum):
    """Asset class classification for trading instruments."""

    CRYPTO = "CRYPTO"
    EQUITY = "EQUITY"


class SignalStatus(str, Enum):
    """Lifecycle status of a trading signal."""

    WAITING = "WAITING"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    TP3_HIT = "TP3_HIT"


class TradeStatus(str, Enum):
    """Status of an open position/trade."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderSide(str, Enum):
    """Side of an order (buy or sell)."""

    BUY = "buy"
    SELL = "sell"


class ExitReason(str, Enum):
    """Reason for trade exit."""

    TP1 = "TP1"
    TP2 = "TP2"
    STOP_LOSS = "STOP_LOSS"
    COLOR_FLIP = "COLOR_FLIP"
    STRUCTURAL_INVALIDATION = "STRUCTURAL_INVALIDATION"
    EXPIRED = "EXPIRED"
    TP_HIT = "TP_HIT"


# =============================================================================
# FIRESTORE: CONFIGURATION DOMAIN (Collection: dim_strategies)
# =============================================================================


class StrategyConfig(BaseModel):
    """
    Strategy configuration stored in Firestore dim_strategies collection.

    Defines the parameters and assets for a trading strategy.
    """

    strategy_id: str = Field(
        ...,
        description="Unique identifier for the strategy",
    )
    active: bool = Field(
        ...,
        description="Whether the strategy is currently active",
    )
    timeframe: str = Field(
        ...,
        description="Trading timeframe (e.g., '1D', '4H', '1H')",
    )
    asset_class: AssetClass = Field(
        ...,
        description="Asset class this strategy trades (CRYPTO or EQUITY)",
    )
    assets: List[str] = Field(
        ...,
        description="List of asset symbols this strategy trades",
    )
    risk_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Risk management parameters (stop_loss_pct, take_profit_pct, etc.)",
    )


# =============================================================================
# FIRESTORE: OPERATIONAL DOMAIN (Collections: live_signals, live_positions)
# =============================================================================


class Signal(BaseModel):
    """
    Trading signal stored in Firestore live_signals collection.

    Represents a potential trade opportunity identified by a strategy.

    WARNING:
        signal_id MUST be a deterministic hash (uuid5) of
        ds + strategy_id + symbol.
        Use get_deterministic_id(f"{ds}|{strategy_id}|{symbol}") to generate it.
        This ensures idempotency - the same signal detected twice
        won't create duplicates.
    """

    signal_id: str = Field(
        ...,
        description="Deterministic UUID5 hash of ds|strategy_id|symbol",
    )
    ds: date = Field(
        ...,
        description="Date stamp when the signal was generated",
    )
    strategy_id: str = Field(
        ...,
        description="Strategy that generated this signal",
    )
    symbol: str = Field(
        ...,
        description="Asset symbol (e.g., 'BTC/USD', 'AAPL')",
    )
    asset_class: AssetClass = Field(
        ...,
        description="Asset class (CRYPTO or EQUITY)",
    )
    confluence_factors: List[str] = Field(
        default_factory=list,
        description="List of triggers/patterns (e.g., 'RSI_DIV', 'VCP_COMPRESSION')",
    )
    entry_price: float = Field(
        ...,
        description="Price at the time signal was triggered (candle close)",
    )
    pattern_name: str = Field(
        ...,
        description="Name of the pattern detected (e.g., 'bullish_engulfing')",
    )
    status: SignalStatus = Field(
        default=SignalStatus.WAITING,
        description="Current lifecycle status of the signal",
    )
    suggested_stop: float = Field(
        ...,
        description="Suggested stop-loss price for this signal",
    )
    expiration_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this signal expires",
    )
    invalidation_price: Optional[float] = Field(
        default=None,
        description="Structure-based invalidation level (early exit)",
    )
    take_profit_1: Optional[float] = Field(
        default=None,
        description="First profit target (Conservative, e.g., 2*ATR)",
    )
    take_profit_2: Optional[float] = Field(
        default=None,
        description="Second profit target (Structural, e.g., 4*ATR)",
    )
    take_profit_3: Optional[float] = Field(
        default=None,
        description="Third profit target (Runner/Moonbag)",
    )
    exit_reason: Optional[ExitReason] = Field(
        default=None,
        description="Reason for trade exit (e.g., ExitReason.TP1)",
    )


class Position(BaseModel):
    """
    Open position/trade stored in Firestore live_positions collection.

    Represents an actual trade executed based on a signal.

    WARNING:
        position_id MUST match the Alpaca Client Order ID for idempotency.
        This ensures we can reconcile positions with the broker and prevent
        duplicate order submissions.
    """

    position_id: str = Field(
        ...,
        description="Must match Alpaca Client Order ID for idempotency",
    )
    ds: date = Field(
        ...,
        description="Date when position was opened",
    )
    account_id: str = Field(
        ...,
        description="Alpaca account ID",
    )
    signal_id: str = Field(
        ...,
        description="Reference to the signal that triggered this position",
    )
    discord_thread_id: Optional[str] = Field(
        default=None,
        description="Discord thread ID for trade notifications",
    )
    status: TradeStatus = Field(
        default=TradeStatus.OPEN,
        description="Current status of the position",
    )
    entry_fill_price: float = Field(
        ...,
        description="Actual fill price at which the position was entered",
    )
    current_stop_loss: float = Field(
        ...,
        description="Current stop-loss price (may be trailed)",
    )
    qty: float = Field(
        ...,
        description="Quantity/size of the position",
    )
    side: OrderSide = Field(
        ...,
        description="Order side (buy or sell)",
    )


# =============================================================================
# BIGQUERY: TRADE EXECUTION (Tables: fact_trades, stg_trades_import)
# =============================================================================


class TradeExecution(BaseModel):
    """
    Completed trade execution record for BigQuery analytics.

    Stored in the fact_trades table, partitioned by ds (date). Used for performance
    analysis and reporting.
    """

    ds: date = Field(
        ...,
        description="Partition key - date of trade execution",
    )
    trade_id: str = Field(
        ...,
        description="Unique identifier for this trade",
    )
    account_id: str = Field(
        ...,
        description="Alpaca account ID",
    )
    strategy_id: str = Field(
        ...,
        description="Strategy that executed this trade",
    )
    asset_class: AssetClass = Field(
        ...,
        description="Asset class traded (CRYPTO or EQUITY)",
    )
    symbol: str = Field(
        ...,
        description="Asset symbol traded",
    )
    side: OrderSide = Field(
        ...,
        description="Order side (buy or sell)",
    )
    qty: float = Field(
        ...,
        description="Quantity traded",
    )
    entry_price: float = Field(
        ...,
        description="Entry fill price",
    )
    exit_price: float = Field(
        ...,
        description="Exit fill price",
    )
    entry_time: datetime = Field(
        ...,
        description="UTC timestamp of entry fill",
    )
    exit_time: datetime = Field(
        ...,
        description="UTC timestamp of exit fill",
    )
    exit_reason: ExitReason = Field(
        ...,
        description="Reason for trade exit (e.g., 'TP1', 'COLOR_FLIP')",
    )
    max_favorable_excursion: Optional[float] = Field(
        default=None,
        description="Highest price reached during trade",
    )
    pnl_pct: float = Field(
        ...,
        description="Profit/Loss as percentage",
    )
    pnl_usd: float = Field(
        ...,
        description="Profit/Loss in USD",
    )
    fees_usd: float = Field(
        ...,
        description="Total fees paid in USD",
    )
    slippage_pct: float = Field(
        ...,
        description="Slippage as percentage of entry price",
    )
    trade_duration: int = Field(
        ...,
        description="Trade duration in seconds",
    )


class StagingTrade(BaseModel):
    """
    Staging model for trade imports to BigQuery.

    Exact mirror of TradeExecution. Validates payloads before loading into the
    stg_trades_import table.
    """

    ds: date = Field(
        ...,
        description="Partition key - date of trade execution",
    )
    trade_id: str = Field(
        ...,
        description="Unique identifier for this trade",
    )
    account_id: str = Field(
        ...,
        description="Alpaca account ID",
    )
    strategy_id: str = Field(
        ...,
        description="Strategy that executed this trade",
    )
    asset_class: AssetClass = Field(
        ...,
        description="Asset class traded (CRYPTO or EQUITY)",
    )
    symbol: str = Field(
        ...,
        description="Asset symbol traded",
    )
    side: OrderSide = Field(
        ...,
        description="Order side (buy or sell)",
    )
    qty: float = Field(
        ...,
        description="Quantity traded",
    )
    entry_price: float = Field(
        ...,
        description="Entry fill price",
    )
    exit_price: float = Field(
        ...,
        description="Exit fill price",
    )
    entry_time: datetime = Field(
        ...,
        description="UTC timestamp of entry fill",
    )
    exit_time: datetime = Field(
        ...,
        description="UTC timestamp of exit fill",
    )
    exit_reason: ExitReason = Field(
        ...,
        description="Reason for trade exit (e.g., 'TP1', 'COLOR_FLIP')",
    )
    max_favorable_excursion: Optional[float] = Field(
        default=None,
        description="Highest price reached during trade",
    )
    pnl_pct: float = Field(
        ...,
        description="Profit/Loss as percentage",
    )
    pnl_usd: float = Field(
        ...,
        description="Profit/Loss in USD",
    )
    fees_usd: float = Field(
        ...,
        description="Total fees paid in USD",
    )
    slippage_pct: float = Field(
        ...,
        description="Slippage as percentage of entry price",
    )
    trade_duration: int = Field(
        ...,
        description="Trade duration in seconds",
    )


# =============================================================================
# BIGQUERY: ACCOUNT SNAPSHOTS (Tables: snapshot_accounts, stg_accounts_import)
# =============================================================================


class AccountSnapshot(BaseModel):
    """
    Account snapshot record for BigQuery analytics.

    Stored in the snapshot_accounts table, partitioned by ds (date). Captures daily
    account metrics for performance tracking.
    """

    ds: date = Field(
        ...,
        description="Partition key - snapshot date",
    )
    account_id: str = Field(
        ...,
        description="Alpaca account ID",
    )
    equity: float = Field(
        ...,
        description="Total account equity in USD",
    )
    cash: float = Field(
        ...,
        description="Available cash in USD",
    )
    calmar_ratio: float = Field(
        ...,
        description="Calmar ratio (annualized return / max drawdown)",
    )
    drawdown_pct: float = Field(
        ...,
        description="Current drawdown percentage from peak",
    )


class StagingAccount(BaseModel):
    """
    Staging model for account snapshots to BigQuery.

    Exact mirror of AccountSnapshot. Validates payloads before loading into the
    stg_accounts_import table.
    """

    ds: date = Field(
        ...,
        description="Partition key - snapshot date",
    )
    account_id: str = Field(
        ...,
        description="Alpaca account ID",
    )
    equity: float = Field(
        ...,
        description="Total account equity in USD",
    )
    cash: float = Field(
        ...,
        description="Available cash in USD",
    )
    calmar_ratio: float = Field(
        ...,
        description="Calmar ratio (annualized return / max drawdown)",
    )
    drawdown_pct: float = Field(
        ...,
        description="Current drawdown percentage from peak",
    )


# =============================================================================
# BIGQUERY: STRATEGY PERFORMANCE
# (Tables: summary_strategy_performance, stg_performance_import)
# =============================================================================


class StrategyPerformance(BaseModel):
    """
    Strategy performance metrics for BigQuery analytics.

    Stored in the summary_strategy_performance table, partitioned by ds (date).
    Aggregated daily performance metrics per strategy.
    """

    ds: date = Field(
        ...,
        description="Partition key - performance date",
    )
    strategy_id: str = Field(
        ...,
        description="Strategy identifier",
    )
    total_trades: int = Field(
        ...,
        description="Total number of trades executed",
    )
    win_rate: float = Field(
        ...,
        description="Percentage of winning trades",
    )
    profit_factor: float = Field(
        ...,
        description="Gross profit / gross loss ratio",
    )
    sharpe_ratio: float = Field(
        ...,
        description="Risk-adjusted return (Sharpe)",
    )
    sortino_ratio: float = Field(
        ...,
        description="Downside risk-adjusted return (Sortino)",
    )
    max_drawdown_pct: float = Field(
        ...,
        description="Maximum drawdown percentage",
    )
    alpha: float = Field(
        ...,
        description="Excess return vs benchmark",
    )
    beta: float = Field(
        ...,
        description="Sensitivity to market movements",
    )


class StagingPerformance(BaseModel):
    """
    Staging model for strategy performance to BigQuery.

    Exact mirror of StrategyPerformance. Validates payloads before loading into the
    stg_performance_import table.
    """

    ds: date = Field(
        ...,
        description="Partition key - performance date",
    )
    strategy_id: str = Field(
        ...,
        description="Strategy identifier",
    )
    total_trades: int = Field(
        ...,
        description="Total number of trades executed",
    )
    win_rate: float = Field(
        ...,
        description="Percentage of winning trades",
    )
    profit_factor: float = Field(
        ...,
        description="Gross profit / gross loss ratio",
    )
    sharpe_ratio: float = Field(
        ...,
        description="Risk-adjusted return (Sharpe)",
    )
    sortino_ratio: float = Field(
        ...,
        description="Downside risk-adjusted return (Sortino)",
    )
    max_drawdown_pct: float = Field(
        ...,
        description="Maximum drawdown percentage",
    )
    alpha: float = Field(
        ...,
        description="Excess return vs benchmark",
    )
    beta: float = Field(
        ...,
        description="Sensitivity to market movements",
    )
