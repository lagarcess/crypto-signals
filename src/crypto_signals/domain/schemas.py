"""
Data Schemas for Crypto Sentinel.

This module defines the strict "Data Contract" between Python logic,
Firestore (NoSQL), and BigQuery (SQL). All models use Pydantic for
validation and serialization.

Architecture Overview (Environment Isolated):
- Firestore Configuration: dim_strategies
- Firestore Operational: live_signals, live_positions, rejected_signals
- Firestore Development: test_signals, test_positions, test_rejected_signals
- BigQuery Analytics: fact_trades, fact_trades_test
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

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

    CREATED = "CREATED"  # Persisted but not yet notified
    WAITING = "WAITING"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    TP3_HIT = "TP3_HIT"
    REJECTED_BY_FILTER = "REJECTED_BY_FILTER"  # Shadow signal: failed quality gate


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
    NOTIFICATION_FAILED = "NOTIFICATION_FAILED"
    MANUAL_EXIT = "MANUAL_EXIT"
    CLOSED_EXTERNALLY = (
        "CLOSED_EXTERNALLY"  # Position closed outside system (State Reconciler)
    )


class TradeType(str, Enum):
    """Classification of trade execution for analytics.

    Clear Semantics:
    - EXECUTED: Real broker order placed and filled (live trading)
    - FILTERED: Rejected by quality gates (Volume, R:R, etc.)
      - Goes to separate analysis Discord channel
      - Tracked for filter tuning analytics
    - THEORETICAL: Execution failed but tracked for performance analysis
      - Broker rejection, validation failure, retries exhausted
      - Appears in LIVE Discord channel (no special indicator to users)
      - Backend tracks full lifecycle for theoretical P&L
    """

    EXECUTED = "EXECUTED"  # Real broker order filled
    FILTERED = "FILTERED"  # Quality gate rejection
    THEORETICAL = "THEORETICAL"  # Execution failed, simulating trade
    RISK_BLOCKED = "RISK_BLOCKED"  # Blocked by RiskEngine (Shadow P&L)


# =============================================================================
# LOGGING AND MONITORING SCHEMAS
# =============================================================================


class BaseLogEntry(BaseModel):
    """Base model for a structured log entry."""

    severity: str
    timestamp: datetime


class JsonPayload(BaseModel):
    """Schema for a JSON payload within a log entry."""

    message: str
    context: Optional[Dict[str, Any]] = None


class LogEntry(BaseLogEntry):
    """Represents a Google Cloud Logging entry."""

    json_payload: Optional[JsonPayload] = Field(None, alias="jsonPayload")
    text_payload: Optional[str] = Field(None, alias="textPayload")

    @property
    def effective_message(self) -> str:
        """Returns the most relevant message from the log entry."""
        if self.json_payload and self.json_payload.message:
            return self.json_payload.message
        return self.text_payload or ""


class ZombieEvent(BaseModel):
    """Schema for identifying a 'Zombie' event in logs."""

    EVENT_TYPE: ClassVar[str] = "Zombie"
    event_type: str = EVENT_TYPE
    details: Dict[str, Any]


class OrphanEvent(BaseModel):
    """Schema for identifying an 'Orphan' event in logs."""

    EVENT_TYPE: ClassVar[str] = "Orphan"
    event_type: str = EVENT_TYPE
    details: Dict[str, Any]


# =============================================================================
# STATE RECONCILIATION DOMAIN (Issue #113)
# =============================================================================


class ReconciliationReport(BaseModel):
    """Report of state reconciliation between Alpaca and Firestore.

    Detects and reports discrepancies between broker state and database state,
    including zombie positions (closed in Alpaca, open in DB) and orphan
    positions (open in Alpaca, missing from DB).
    """

    zombies: List[str] = Field(
        default_factory=list,
        description="Symbols closed in Alpaca but marked OPEN in Firestore",
    )
    orphans: List[str] = Field(
        default_factory=list,
        description="Symbols with open positions in Alpaca but no Firestore record",
    )
    reconciled_count: int = Field(
        default=0,
        description="Number of positions updated during reconciliation",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When reconciliation was performed",
    )
    duration_seconds: float = Field(
        default=0.0,
        description="Time taken to run reconciliation (seconds)",
    )
    critical_issues: List[str] = Field(
        default_factory=list,
        description="Critical alerts (e.g., orphan positions)",
    )


# =============================================================================
# FIRESTORE: CONFIGURATION DOMAIN (Collection: dim_strategies)
# =============================================================================


class ConfluenceConfig(BaseModel):
    """Configuration for confluence factors."""
    rsi_threshold: Optional[float] = None
    volume_multiplier: Optional[float] = None


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
    confluence_config: ConfluenceConfig = Field(
        default_factory=ConfluenceConfig,
        description="Configuration for confluence factors (e.g., RSI thresholds, Volume multipliers)",
    )
    pattern_overrides: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Symbol-specific overrides for pattern parameters (e.g., custom stop loss for BTC)",
    )


# =============================================================================
# FIRESTORE: OPERATIONAL DOMAIN (Collections: live_signals, live_positions)
# =============================================================================


class Signal(BaseModel):
    """
    Trading signal stored in Firestore live_signals collection.

    Represents a potential trade opportunity identified by a strategy.

    The Signal model is the primary carrier of thread identity for Discord
    notifications. The discord_thread_id links all lifecycle updates
    (TP hits, invalidations, expirations, runner exits) back to the original
    broadcast message, enabling traders to follow the complete narrative of
    a single trade in one thread.

    IMPORTANT - Time Fields:
        - valid_until: Logical expiration (24h from candle close). Use this
          for expiration checks: `if now > signal.valid_until: # EXPIRE`
          DO NOT use `sig.ds + timedelta(days=1)` - that ignores time component.
        - delete_at: Physical TTL for GCP Firestore cleanup (30 days for live,
          7 days for rejected signals). Do not use for business logic.

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
    valid_until: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Logical expiration of the trading opportunity (24h window from candle close)",
    )
    delete_at: Optional[datetime] = Field(
        default=None,
        description="Physical expiration for database TTL cleanup (30 days). Used by GCP TTL policy.",
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
        description="Current volatility-adjusted trailing stop (Chandelier Exit) for Runner positions",
    )
    exit_reason: Optional[ExitReason] = Field(
        default=None,
        description="Reason for trade exit (e.g., ExitReason.TP1)",
    )
    discord_thread_id: Optional[str] = Field(
        default=None,
        description="Discord thread ID for linking all lifecycle updates back to the original broadcast",
    )
    side: Optional[OrderSide] = Field(
        default=OrderSide.BUY,
        description="Trade direction (BUY for Long, SELL for Short). Defaults to BUY for backward compatibility.",
    )
    # === Structural Pattern Metadata (Phase 7) ===
    pattern_duration_days: Optional[int] = Field(
        default=None,
        description="Duration in days from first pivot to signal (for MACRO classification)",
    )
    pattern_span_days: Optional[int] = Field(
        default=None,
        description="Time span from first to last structural pivot in the pattern (geometric extent)",
    )
    pattern_classification: Optional[str] = Field(
        default=None,
        description="Pattern scale: 'STANDARD_PATTERN' (5-90 days) or 'MACRO_PATTERN' (>90 days)",
    )
    structural_anchors: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of structural pivots defining pattern geometry: [{price, timestamp, pivot_type}]",
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Reason for rejection if status is REJECTED_BY_FILTER (e.g., 'Volume 1.2x < 1.5x Required')",
    )
    rejection_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Forensic data for validation failures (e.g., raw invalid stops for audit)",
    )
    confluence_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Snapshot of indicator values at rejection: {rsi, adx, sma_trend, volume_ratio, rr_ratio}",
    )
    # === Harmonic Pattern Metadata ===
    harmonic_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Harmonic pattern ratios for Fibonacci-based patterns: {B_ratio, D_ratio, wave3_to_wave1_ratio, etc.}",
    )
    # === Signal Age Tracking (Issue 99 Fix) ===
    created_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp when signal was created. Used for skip-on-creation cooldown in check_exits.",
    )
    # === Trade Lifecycle Classification (Issue 107) ===
    trade_type: Optional[str] = Field(
        default="EXECUTED",
        description=(
            "Trade classification: EXECUTED (broker order filled), "
            "FILTERED (quality gate rejection), THEORETICAL (execution failed, simulating)."
        ),
    )

    @model_validator(mode="after")
    def set_fallback_created_at(self) -> "Signal":
        """
        Fallback for legacy signals missing created_at.

        Legacy signals (pre-fix) had valid_until set to created_at + TTL.
        New dynamic TTL: 48h for STANDARD patterns, 120h for MACRO patterns.

        We use pattern_classification to determine the correct TTL, falling back
        to the maximum TTL (120h) for safety if classification is unknown. This
        ensures the cooldown gate works correctly even if created_at is slightly
        off - erring on the side of skipping signals is safer than premature exit.
        """
        if self.created_at is None and self.valid_until:
            # Determine TTL based on pattern classification
            is_macro = (
                self.pattern_classification and "MACRO" in self.pattern_classification
            )
            ttl_hours = 120 if is_macro else 48
            # For legacy signals without classification, use conservative 120h
            if self.pattern_classification is None:
                ttl_hours = 120
            self.created_at = self.valid_until - timedelta(hours=ttl_hours)
        return self


class Position(BaseModel):
    """
    Open position/trade stored in Firestore live_positions collection.

    Represents an actual trade executed based on a Signal via the ExecutionEngine.

    Key Relationships:
        - position_id: Set to signal_id for idempotency. Also used as
          client_order_id when submitting to Alpaca.
        - signal_id: Reference back to the originating Signal document.
        - alpaca_order_id: Parent bracket order ID from Alpaca.
        - tp_order_id / sl_order_id: TP/SL leg IDs (populated after fill).

    Order Management Fields:
        - target_entry_price: Original signal price (for slippage calculation)
        - filled_at: Precision timestamp from Alpaca API
        - commission: Broker-reported fees
        - failed_reason: Error message if order rejected/canceled

    Example:
        Signal generates -> ExecutionEngine submits bracket order ->
        Position created with position_id = signal_id, alpaca_order_id = order.id
        -> sync_position_status() extracts tp_order_id/sl_order_id after fill
    """

    position_id: str = Field(
        ...,
        description=(
            "Unique position identifier. Set to signal_id to ensure idempotency "
            "and allow duplicate detection."
        ),
    )
    ds: date = Field(
        ...,
        description="Date when position was opened",
    )
    account_id: str = Field(
        ...,
        description="Alpaca account ID (e.g., 'paper' for paper trading)",
    )
    symbol: str = Field(
        ...,
        description="Trading symbol (e.g., 'BTC/USD', 'NVDA'). Required for emergency closes.",
    )
    signal_id: str = Field(
        ...,
        description="Reference to the Signal that triggered this position",
    )
    alpaca_order_id: Optional[str] = Field(
        default=None,
        description=(
            "Alpaca's order ID returned after order submission. "
            "Used for order status queries and reconciliation."
        ),
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
    trailing_stop_final: Optional[float] = Field(
        default=None,
        description="Final trailing stop value at exit (Chandelier Exit for TP3)",
    )
    # === New fields for Order Management (Managed Trade Model) ===
    tp_order_id: Optional[str] = Field(
        default=None,
        description=(
            "Alpaca order ID for the Take Profit leg. "
            "Populated after parent bracket order fills via sync_position_status."
        ),
    )
    sl_order_id: Optional[str] = Field(
        default=None,
        description=(
            "Alpaca order ID for the Stop Loss leg. "
            "Populated after parent bracket order fills via sync_position_status."
        ),
    )
    target_entry_price: Optional[float] = Field(
        default=None,
        description=(
            "Original signal's entry price (target). "
            "Compare against entry_fill_price for slippage calculation."
        ),
    )
    filled_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp when entry order was filled. From Alpaca API.",
    )
    commission: float = Field(
        default=0.0,
        description="Total commission/fees reported by broker for this position.",
    )
    failed_reason: Optional[str] = Field(
        default=None,
        description="Error message if order was rejected or canceled by broker.",
    )
    exit_fill_price: Optional[float] = Field(
        default=None,
        description="Actual exit fill price from TP or SL order. From Alpaca API.",
    )
    exit_time: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp when exit order was filled. From Alpaca API.",
    )
    exit_reason: Optional[ExitReason] = Field(
        default=None,
        description="Reason for trade exit (e.g., TP1, STOP_LOSS, MANUAL_EXIT).",
    )
    exit_order_id: Optional[str] = Field(
        default=None,
        description="Alpaca order ID for the exit order. Used for reconciliation and fill tracking.",
    )
    # === CFEE Tracking Fields (Issue #140) ===
    entry_order_id: Optional[str] = Field(
        default=None,
        description="Entry order ID for CFEE attribution. Captured from Alpaca order response.",
    )
    exit_commission: Optional[float] = Field(
        default=None,
        description="Commission from exit order(s). Sum of all scale-out commissions.",
    )
    total_fees_actual: Optional[float] = Field(
        default=None,
        description="Actual fees from Alpaca CFEE activities (crypto only). Populated during T+1 reconciliation.",
    )
    awaiting_backfill: bool = Field(
        default=False,
        description=(
            "Flag indicating exit fill price is pending backfill. "
            "Set to True if retry budget exhausted, cleared by sync_position_status()."
        ),
    )

    # === Trade Lifecycle Classification (Issue 107) ===
    trade_type: Optional[str] = Field(
        default="EXECUTED",
        description=(
            "Trade classification: EXECUTED (broker order filled), "
            "THEORETICAL (execution failed, tracking simulated P&L)."
        ),
    )
    # === Scale-Out Tracking (TP1 automation) ===
    original_qty: Optional[float] = Field(
        default=None,
        description="Original quantity before any scale-outs. Set on entry fill.",
    )
    scaled_out_qty: float = Field(
        default=0.0,
        description="Total quantity scaled out (closed at TP1). For PnL calc.",
    )
    scaled_out_price: Optional[float] = Field(
        default=None,
        description="Average fill price of scale-out exit at TP1.",
    )
    scaled_out_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of scale-out execution.",
    )
    breakeven_applied: bool = Field(
        default=False,
        description="Whether stop was moved to breakeven after TP1.",
    )
    scaled_out_prices: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="History of scale-outs: [{qty, price, timestamp}] for multi-stage PnL.",
    )
    # === Real-time Analytics Fields ===
    entry_slippage_pct: Optional[float] = Field(
        default=None,
        description="Entry slippage: (entry_fill_price - target_entry_price) / target_entry_price * 100",
    )
    exit_slippage_pct: Optional[float] = Field(
        default=None,
        description="Exit slippage: (exit_fill_price - target_exit_price) / target_exit_price * 100",
    )
    trade_duration_seconds: Optional[int] = Field(
        default=None,
        description="Trade duration in seconds from filled_at to exit_time.",
    )
    realized_pnl_usd: float = Field(
        default=0.0,
        description="Aggregate realized PnL in USD (includes scale-outs). Updated in real-time.",
    )
    realized_pnl_pct: float = Field(
        default=0.0,
        description="Aggregate realized PnL as percentage of entry. Updated in real-time.",
    )
    # === TTL for GCP Firestore Cleanup ===
    delete_at: Optional[datetime] = Field(
        default=None,
        description=(
            "Physical expiration for database TTL cleanup (90 days). "
            "Used by GCP TTL policy and populated at creation time "
            "by the execution layer (driven by config.py)."
        ),
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
    discord_thread_id: Optional[str] = Field(
        default=None,
        description="Discord thread ID for social context analytics",
    )
    trailing_stop_final: Optional[float] = Field(
        default=None,
        description="Final trailing stop value at exit (Chandelier Exit for TP3)",
    )
    target_entry_price: Optional[float] = Field(
        default=None,
        description="Original signal's entry price (target). Compare against entry_price for slippage.",
    )
    alpaca_order_id: Optional[str] = Field(
        default=None,
        description="Alpaca broker's UUID for the entry order. Links to Alpaca dashboard for auditability.",
    )
    exit_order_id: Optional[str] = Field(
        default=None,
        description="Alpaca broker's UUID for the exit order. Used for reconciliation and fill tracking.",
    )
    # === CFEE Reconciliation Fields (Issue #140) ===
    fee_finalized: bool = Field(
        default=False,
        description="Whether actual fees have been reconciled from Alpaca CFEE activities (T+1 settlement)",
    )
    actual_fee_usd: Optional[float] = Field(
        default=None,
        description="Actual fee from Alpaca CFEE (T+1 settlement). Replaces estimated fees_usd after reconciliation.",
    )
    fee_calculation_type: str = Field(
        default="ESTIMATED",
        description="Source of fee data: 'ESTIMATED' (initial), 'ACTUAL_CFEE' (from Activities API), 'ACTUAL_COMMISSION' (from order)",
    )
    fee_tier: Optional[str] = Field(
        default=None,
        description="Alpaca volume tier at time of trade (e.g., 'Tier 0: 0.25%'). Used for fee estimation and audit.",
    )
    entry_order_id: Optional[str] = Field(
        default=None,
        description="Entry order ID for CFEE attribution (from Issue #139). Used to match CFEE activities to trades.",
    )
    fee_reconciled_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when fees were reconciled from CFEE. NULL if still using estimates.",
    )
    # === Intermediate Fields (Excluded from BigQuery) ===
    scaled_out_prices: List[Dict[str, Any]] = Field(
        default_factory=list,
        exclude=True,
        description="History of scale-outs used for weighted average calculation. Not persisted to BQ.",
    )
    original_qty: Optional[float] = Field(
        default=None,
        exclude=True,
        description="Original quantity before any scale-outs. Used for weighted average calculation. Not persisted to BQ.",
    )

    @model_validator(mode="before")
    @classmethod
    def calculate_weighted_exit_price(cls, data: Any) -> Any:
        """
        Calculate weighted average exit price if scale-outs are present.

        Also ensures pnl_usd and pnl_pct are consistent with the weighted price.
        """
        if isinstance(data, dict):
            scaled_outs = data.get("scaled_out_prices", [])
            if not scaled_outs:
                return data

            total_exit_val = 0.0
            total_exit_qty = 0.0

            for scale in scaled_outs:
                s_qty = float(scale.get("qty", 0.0))
                s_price = float(scale.get("price", 0.0))
                total_exit_val += s_qty * s_price
                total_exit_qty += s_qty

            total_qty = float(data.get("original_qty") or data.get("qty") or 0.0)

            if total_qty <= 0:
                return data

            final_exit_price = float(data.get("exit_price") or 0.0)
            remaining_qty = total_qty - total_exit_qty

            if remaining_qty > 0:
                total_exit_val += remaining_qty * final_exit_price

            # 1. Update Exit Price
            weighted_exit_price = total_exit_val / total_qty
            data["exit_price"] = weighted_exit_price

            # 2. Re-calculate PnL to ensure consistency (Issue #149)
            # We must use the same logic as the transformation layer but here
            # to guarantee the BigQuery record is accurate.
            entry_price = float(data.get("entry_price", 0.0))
            fees_usd = float(data.get("fees_usd", 0.0))
            side = str(data.get("side", "buy")).lower()

            # Simple PnL recalculation based on side
            if side == "buy":
                pnl_gross = (weighted_exit_price - entry_price) * total_qty
            else:
                pnl_gross = (entry_price - weighted_exit_price) * total_qty

            pnl_net = pnl_gross - fees_usd

            # Update data dict
            data["pnl_usd"] = round(pnl_net, 4)
            if entry_price and total_qty:
                data["pnl_pct"] = round((pnl_net / (entry_price * total_qty)) * 100, 4)

        return data


class ExpiredSignal(BaseModel):
    """
    Archived expired signal for BigQuery analytics.

    Stored in the fact_signals_expired table. Used for analyzing signal
    sensitivity and "near misses".
    """

    doc_id: Optional[str] = Field(None, description="Firestore document ID")
    ds: date = Field(..., description="Partition key - date signal was generated")
    signal_id: str = Field(..., description="Unique identifier for the signal")
    strategy_id: str = Field(..., description="Strategy that generated the signal")
    symbol: str = Field(..., description="Asset symbol")
    asset_class: AssetClass = Field(..., description="Asset class (CRYPTO or EQUITY)")
    side: OrderSide = Field(..., description="Signal side (buy or sell)")
    entry_price: float = Field(..., description="Target entry price of the signal")
    suggested_stop: float = Field(..., description="Suggested stop-loss for the signal")
    valid_until: datetime = Field(..., description="When the signal expired")
    max_mfe_during_validity: Optional[float] = Field(
        default=None,
        description="Max favorable excursion during validity (Highest High - Entry for BUYs)",
    )
    distance_to_trigger_pct: Optional[float] = Field(
        default=None,
        description="Percentage distance from entry to trigger ((Entry - Highest High) / Entry for BUYs)",
    )


class FactRejectedSignal(BaseModel):
    """
    Schema for rejected signals archival (Fact Table).

    This matches the `fact_rejected_signals` BigQuery table.
    """

    doc_id: Optional[str] = Field(None, description="Firestore document ID")
    ds: date
    signal_id: str
    symbol: str
    asset_class: str
    pattern_name: str
    rejection_reason: str
    trade_type: str
    side: str
    entry_price: float
    suggested_stop: float
    take_profit_1: float
    theoretical_exit_price: Optional[float]
    theoretical_exit_reason: Optional[str]
    theoretical_exit_time: Optional[datetime]
    theoretical_pnl_usd: float
    theoretical_pnl_pct: float
    theoretical_fees_usd: float
    created_at: datetime


class RejectedSignal(BaseModel):
    """
    Archived rejected signal for BigQuery analytics.
    """

    ds: date
    signal_id: str
    created_at: datetime


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
    discord_thread_id: Optional[str] = Field(
        default=None,
        description="Discord thread ID for social context analytics",
    )
    trailing_stop_final: Optional[float] = Field(
        default=None,
        description="Final trailing stop value at exit (Chandelier Exit for TP3)",
    )
    target_entry_price: Optional[float] = Field(
        default=None,
        description="Original signal's entry price (target). Compare against entry_price for slippage.",
    )
    alpaca_order_id: Optional[str] = Field(
        default=None,
        description="Alpaca broker's UUID for the entry order. Links to Alpaca dashboard for auditability.",
    )
    exit_order_id: Optional[str] = Field(
        default=None,
        description="Alpaca broker's UUID for the exit order. Used for reconciliation and fill tracking.",
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
    # === NEW FIELDS (Issue 116) ===
    buying_power: Optional[float] = Field(
        default=None,
        description="Current available buying power (Reg T)",
    )
    regt_buying_power: Optional[float] = Field(
        default=None,
        description="Reg T buying power",
    )
    daytrading_buying_power: Optional[float] = Field(
        default=None,
        description="Day trading buying power",
    )
    crypto_buying_power: Optional[float] = Field(
        default=None,
        description="Non-marginable buying power (Crypto BP)",
    )
    initial_margin: Optional[float] = Field(
        default=None,
        description="Initial margin requirement",
    )
    maintenance_margin: Optional[float] = Field(
        default=None,
        description="Maintenance margin requirement",
    )
    last_equity: Optional[float] = Field(
        default=None,
        description="Equity value at last close",
    )
    long_market_value: Optional[float] = Field(
        default=None,
        description="Total market value of long positions",
    )
    short_market_value: Optional[float] = Field(
        default=None,
        description="Total market value of short positions",
    )
    currency: Optional[str] = Field(
        default=None,
        description="Account currency (e.g., USD)",
    )
    status: Optional[str] = Field(
        default=None,
        description="Account status (e.g., ACTIVE)",
    )
    pattern_day_trader: Optional[bool] = Field(
        default=None,
        description="Pattern Day Trader (PDT) flag",
    )
    daytrade_count: Optional[int] = Field(
        default=None,
        description="Number of day trades in last 5 days",
    )
    account_blocked: Optional[bool] = Field(
        default=None,
        description="Whether account is blocked",
    )
    trade_suspended_by_user: Optional[bool] = Field(
        default=None,
        description="Whether trading is suspended by user",
    )
    trading_blocked: Optional[bool] = Field(
        default=None,
        description="Whether trading is blocked",
    )
    transfers_blocked: Optional[bool] = Field(
        default=None,
        description="Whether transfers are blocked",
    )
    multiplier: Optional[float] = Field(
        default=None,
        description="Account leverage multiplier",
    )
    sma: Optional[float] = Field(
        default=None,
        description="SMA value (Special Memorandum Account)",
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
    # === NEW FIELDS (Issue 116) ===
    buying_power: Optional[float] = Field(
        default=None,
        description="Current available buying power (Reg T)",
    )
    regt_buying_power: Optional[float] = Field(
        default=None,
        description="Reg T buying power",
    )
    daytrading_buying_power: Optional[float] = Field(
        default=None,
        description="Day trading buying power",
    )
    crypto_buying_power: Optional[float] = Field(
        default=None,
        description="Non-marginable buying power (Crypto BP)",
    )
    initial_margin: Optional[float] = Field(
        default=None,
        description="Initial margin requirement",
    )
    maintenance_margin: Optional[float] = Field(
        default=None,
        description="Maintenance margin requirement",
    )
    last_equity: Optional[float] = Field(
        default=None,
        description="Equity value at last close",
    )
    long_market_value: Optional[float] = Field(
        default=None,
        description="Total market value of long positions",
    )
    short_market_value: Optional[float] = Field(
        default=None,
        description="Total market value of short positions",
    )
    currency: Optional[str] = Field(
        default=None,
        description="Account currency (e.g., USD)",
    )
    status: Optional[str] = Field(
        default=None,
        description="Account status (e.g., ACTIVE)",
    )
    pattern_day_trader: Optional[bool] = Field(
        default=None,
        description="Pattern Day Trader (PDT) flag",
    )
    daytrade_count: Optional[int] = Field(
        default=None,
        description="Number of day trades in last 5 days",
    )
    account_blocked: Optional[bool] = Field(
        default=None,
        description="Whether account is blocked",
    )
    trade_suspended_by_user: Optional[bool] = Field(
        default=None,
        description="Whether trading is suspended by user",
    )
    trading_blocked: Optional[bool] = Field(
        default=None,
        description="Whether trading is blocked",
    )
    transfers_blocked: Optional[bool] = Field(
        default=None,
        description="Whether transfers are blocked",
    )
    multiplier: Optional[float] = Field(
        default=None,
        description="Account leverage multiplier",
    )
    sma: Optional[float] = Field(
        default=None,
        description="SMA value (Special Memorandum Account)",
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


# =============================================================================
# BIGQUERY: STRATEGY SCD TYPE 2 (Tables: dim_strategies, stg_strategies_import)
# =============================================================================


class StagingStrategy(BaseModel):
    """
    Staging model for Strategy Configuration (SCD Type 2).

    This matches the target `dim_strategies` table schema but is used for staging
    and merge operations.
    """

    strategy_id: str = Field(
        ...,
        description="Natural key: Strategy identifier",
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
    risk_params: str = Field(
        ...,
        description="JSON string representation of risk management parameters",
    )
    config_hash: str = Field(
        ...,
        description="Hash of the configuration to detect changes",
    )
    valid_from: datetime = Field(
        ...,
        description="SCD2: Start of validity period",
    )
    valid_to: Optional[datetime] = Field(
        default=None,
        description="SCD2: End of validity period (NULL for current)",
    )
    is_current: bool = Field(
        default=True,
        description="SCD2: Flag for current record",
    )
