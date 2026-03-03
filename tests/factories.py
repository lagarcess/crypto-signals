from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from crypto_signals.domain.schemas import AssetClass, OrderSide, Position, Signal, SignalStatus, TradeStatus
from polyfactory.factories.pydantic_factory import ModelFactory


class SignalFactory(ModelFactory[Signal]):
    __model__ = Signal

    @classmethod
    def signal_id(cls) -> str:
        return "test-signal-123"

    @classmethod
    def ds(cls) -> date:
        return date(2025, 1, 15)

    strategy_id = "BULLISH_ENGULFING"
    symbol = "BTC/USD"
    asset_class = AssetClass.CRYPTO
    entry_price = 50000.0
    pattern_name = "BULLISH_ENGULFING"
    suggested_stop = 48000.0
    status = SignalStatus.WAITING
    take_profit_1 = 55000.0
    take_profit_2 = 60000.0
    side = OrderSide.BUY

    @classmethod
    def valid_until(cls) -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=1)

    @classmethod
    def created_at(cls) -> datetime:
        return datetime.now(timezone.utc) - timedelta(hours=1)

    @classmethod
    def scaled_out_prices(cls) -> List[Dict[str, Any]]:
        return []

    # Optional fields should default to None to avoid random values in tests
    invalidation_price = None
    take_profit_3 = None
    delete_at = None
    exit_reason = None
    discord_thread_id = None
    pattern_duration_days = None
    pattern_span_days = None
    pattern_classification = None
    structural_anchors = None
    rejection_reason = None
    rejection_metadata = None
    confluence_snapshot = None
    harmonic_metadata = None
    structural_context = None
    conviction_tier = None
    trade_type = "EXECUTED"


class PositionFactory(ModelFactory[Position]):
    __model__ = Position

    @classmethod
    def position_id(cls) -> str:
        return "test-signal-123"

    @classmethod
    def ds(cls) -> date:
        return date(2025, 1, 15)

    account_id = "paper"
    symbol = "BTC/USD"
    asset_class = AssetClass.CRYPTO
    signal_id = "test-signal-123"
    status = TradeStatus.OPEN
    entry_fill_price = 50000.0
    current_stop_loss = 48000.0
    qty = 0.01
    side = OrderSide.BUY
    target_entry_price = 50000.0

    @classmethod
    def created_at(cls) -> datetime:
        return datetime.now(timezone.utc) - timedelta(hours=1)

    @classmethod
    def scaled_out_prices(cls) -> List[Dict[str, Any]]:
        return []

    # Optional fields should default to None to avoid random values in tests
    alpaca_order_id = None
    discord_thread_id = None
    trailing_stop_final = None
    tp_order_id = None
    sl_order_id = None
    filled_at = None
    commission = 0.0
    failed_reason = None
    exit_fill_price = None
    exit_time = None
    exit_reason = None
    exit_order_id = None
    entry_order_id = None
    exit_commission = None
    total_fees_actual = None
    awaiting_backfill = False
    trade_type = "EXECUTED"
    original_qty = None
    scaled_out_qty = 0.0
    scaled_out_price = None
    scaled_out_at = None
    breakeven_applied = False
    entry_slippage_pct = None
    exit_slippage_pct = None
    trade_duration_seconds = None
    realized_pnl_usd = 0.0
    realized_pnl_pct = 0.0
    delete_at = None
