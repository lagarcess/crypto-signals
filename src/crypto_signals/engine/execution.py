"""
Execution Engine for Alpaca Bracket Order Management.

This module bridges Signal objects to live Alpaca trades using Bracket Orders
for atomic Entry, Take-Profit, and Stop-Loss management.
"""

from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)
from crypto_signals.config import get_settings, get_trading_client
from crypto_signals.domain.schemas import (
    AssetClass,
    Position,
    Signal,
    TradeStatus,
)
from crypto_signals.domain.schemas import (
    OrderSide as DomainOrderSide,
)
from crypto_signals.observability import console
from loguru import logger
from rich.panel import Panel


class ExecutionEngine:
    """
    Manages the order lifecycle from Signal to live Alpaca trade.

    Uses Bracket Orders to atomically set Entry, Take Profit, and Stop Loss.
    """

    def __init__(self, trading_client: Optional[TradingClient] = None):
        """
        Initialize the ExecutionEngine.

        Args:
            trading_client: Optional TradingClient for dependency injection.
                           If not provided, uses get_trading_client().
        """
        self.settings = get_settings()
        self._client = trading_client

    @property
    def client(self) -> TradingClient:
        """Lazy-load trading client."""
        if self._client is None:
            self._client = get_trading_client()
        return self._client

    def execute_signal(self, signal: Signal) -> Optional[Position]:
        """
        Execute a trading signal by submitting a Bracket Order to Alpaca.

        Args:
            signal: The Signal object containing entry, TP, and SL levels.

        Returns:
            Position: The created Position object if successful, None otherwise.
        """
        # Safety check: Only execute in paper trading mode
        if not self.settings.is_paper_trading:
            logger.warning(
                "Execution blocked: ALPACA_PAPER_TRADING must be True. "
                "Set ALPACA_PAPER_TRADING=True to enable order execution."
            )
            return None

        # Safety check: Execution must be explicitly enabled
        if not getattr(self.settings, "ENABLE_EXECUTION", False):
            logger.debug(
                "Execution disabled: Set ENABLE_EXECUTION=True to execute orders."
            )
            return None

        # Validate required signal fields
        if not self._validate_signal(signal):
            return None

        try:
            # Calculate position size
            qty = self._calculate_qty(signal)
            if qty <= 0:
                logger.error(f"Invalid quantity calculated for {signal.symbol}: {qty}")
                return None

            # Determine order side
            alpaca_side = (
                OrderSide.BUY if signal.side == DomainOrderSide.BUY else OrderSide.SELL
            )

            # Convert symbol format for Alpaca (BTC/USD -> BTCUSD for crypto)
            alpaca_symbol = self._convert_symbol(signal.symbol, signal.asset_class)

            # Build the Bracket Order request
            order_request = MarketOrderRequest(
                symbol=alpaca_symbol,
                qty=qty,
                side=alpaca_side,
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=round(signal.take_profit_1, 2)),
                stop_loss=StopLossRequest(stop_price=round(signal.suggested_stop, 2)),
                client_order_id=signal.signal_id,  # Traceability link
            )

            # Submit the order
            logger.info(
                f"Submitting bracket order for {signal.symbol}",
                extra={
                    "symbol": signal.symbol,
                    "qty": qty,
                    "side": alpaca_side.value,
                    "take_profit": signal.take_profit_1,
                    "stop_loss": signal.suggested_stop,
                    "client_order_id": signal.signal_id,
                },
            )

            order = self.client.submit_order(order_request)

            # Log success
            logger.info(
                f"ORDER SUBMITTED: {signal.symbol}",
                extra={
                    "order_id": str(order.id),
                    "client_order_id": order.client_order_id,
                    "qty": qty,
                    "status": str(order.status),
                },
            )

            # Create Position object for persistence
            position = Position(
                position_id=signal.signal_id,  # Match client_order_id for idempotency
                ds=signal.ds,
                account_id=str(order.id),  # Store Alpaca order ID here
                signal_id=signal.signal_id,
                discord_thread_id=signal.discord_thread_id,
                status=TradeStatus.OPEN,
                entry_fill_price=signal.entry_price,  # Will update on fill
                current_stop_loss=signal.suggested_stop,
                qty=qty,
                side=signal.side or DomainOrderSide.BUY,
            )

            return position

        except Exception as e:
            self._log_execution_failure(signal, e)
            return None

    def _validate_signal(self, signal: Signal) -> bool:
        """Validate that signal has required fields for execution."""
        errors = []

        if not signal.take_profit_1:
            errors.append("take_profit_1 is required for bracket order")

        if not signal.suggested_stop:
            errors.append("suggested_stop is required for bracket order")

        if not signal.entry_price or signal.entry_price <= 0:
            errors.append("entry_price must be positive")

        if errors:
            logger.error(
                f"Signal validation failed for {signal.symbol}: {', '.join(errors)}"
            )
            return False

        return True

    def _calculate_qty(self, signal: Signal) -> float:
        """
        Calculate position size based on risk configuration.

        Uses RISK_PER_TRADE divided by entry price to determine quantity.
        For crypto, allows fractional quantities.
        """
        risk_per_trade = getattr(self.settings, "RISK_PER_TRADE", 100.0)

        # Simple calculation: risk_amount / entry_price
        qty = risk_per_trade / signal.entry_price

        # Round based on asset class
        if signal.asset_class == AssetClass.CRYPTO:
            # Crypto allows fractional shares (up to 8 decimals for most)
            return round(qty, 6)
        else:
            # Equities: Alpaca supports fractional, round to 4 decimals
            return round(qty, 4)

    def _convert_symbol(self, symbol: str, asset_class: AssetClass) -> str:
        """
        Convert symbol format to Alpaca's expected format.

        Crypto: BTC/USD -> BTCUSD (or BTC/USD depending on Alpaca version)
        Equity: AAPL -> AAPL (no change)
        """
        if asset_class == AssetClass.CRYPTO:
            # Alpaca crypto symbols can use either format, but slash is standard
            # Keep as-is since alpaca-py handles both formats
            return symbol
        return symbol

    def _log_execution_failure(self, signal: Signal, error: Exception) -> None:
        """Display Rich error panel for execution failures."""
        error_content = (
            f"[bold red]Symbol:[/] {signal.symbol}\n"
            f"[bold red]Signal ID:[/] {signal.signal_id}\n"
            f"[bold red]Error:[/] {str(error)}"
        )

        panel = Panel(
            error_content,
            title="[bold white on red] ORDER EXECUTION FAILED [/]",
            border_style="red",
            padding=(1, 2),
        )
        console.print(panel)

        logger.error(
            f"Order execution failed for {signal.symbol}: {error}",
            extra={
                "symbol": signal.symbol,
                "signal_id": signal.signal_id,
                "error": str(error),
            },
        )
