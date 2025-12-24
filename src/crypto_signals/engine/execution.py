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

            # Determine order side (with None fallback)
            effective_side = signal.side or DomainOrderSide.BUY
            alpaca_side = (
                OrderSide.BUY if effective_side == DomainOrderSide.BUY else OrderSide.SELL
            )

            # Build the Bracket Order request
            order_request = MarketOrderRequest(
                symbol=signal.symbol,  # Alpaca accepts BTC/USD format
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

            position = Position(
                position_id=signal.signal_id,
                ds=signal.ds,
                account_id="paper",  # TODO: Fetch from client.get_account().id
                signal_id=signal.signal_id,
                alpaca_order_id=str(order.id),
                discord_thread_id=signal.discord_thread_id,
                status=TradeStatus.OPEN,
                entry_fill_price=signal.entry_price,
                current_stop_loss=signal.suggested_stop,
                qty=qty,
                side=effective_side,
                # New: Capture target price for slippage calculation
                target_entry_price=signal.entry_price,
                # TP/SL leg IDs populated later by sync_position_status
                tp_order_id=None,
                sl_order_id=None,
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

        if not signal.suggested_stop or signal.suggested_stop <= 0:
            errors.append("suggested_stop must be positive")

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
        Calculate position size based on fixed dollar risk.

        Uses the formula: qty = RISK_PER_TRADE / risk_per_share
        where risk_per_share = |entry_price - stop_loss|

        This ensures that if the stop loss is hit, you lose exactly
        RISK_PER_TRADE dollars (before slippage/fees).

        For crypto, allows fractional quantities (6 decimals).
        For equities, uses 4 decimal precision.
        """
        risk_per_trade = getattr(self.settings, "RISK_PER_TRADE", 100.0)

        # Calculate risk per share (distance from entry to stop)
        risk_per_share = abs(signal.entry_price - signal.suggested_stop)

        if risk_per_share <= 0:
            logger.error(
                f"Invalid risk distance for {signal.symbol}: "
                f"entry={signal.entry_price}, stop={signal.suggested_stop}"
            )
            return 0.0

        # Position size = total risk / risk per share
        qty = risk_per_trade / risk_per_share

        # Round based on asset class
        if signal.asset_class == AssetClass.CRYPTO:
            # Crypto allows fractional shares (up to 8 decimals for most)
            return round(qty, 6)
        else:
            # Equities: Alpaca supports fractional, round to 4 decimals
            return round(qty, 4)

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

    # =========================================================================
    # ORDER MANAGEMENT METHODS (Managed Trade Model)
    # =========================================================================

    def get_order_details(self, order_id: str) -> Optional[object]:
        """
        Retrieve order details from Alpaca by order ID.

        Uses GET /v2/orders/{order_id} endpoint.

        Args:
            order_id: The Alpaca order ID (UUID string).

        Returns:
            Order object if found, None if not found or on error.
        """
        try:
            order = self.client.get_order_by_id(order_id)
            logger.debug(
                f"Retrieved order {order_id}: status={order.status}",
                extra={"order_id": order_id, "status": str(order.status)},
            )
            return order
        except Exception as e:
            # Check for 404/not found
            error_str = str(e).lower()
            if "not found" in error_str or "404" in error_str:
                logger.warning(f"Order {order_id} not found in Alpaca")
                return None
            logger.error(f"Failed to retrieve order {order_id}: {e}")
            return None

    def sync_position_status(self, position: Position) -> Position:
        """
        Synchronize position with Alpaca broker state.

        Fetches the parent order and extracts:
        - TP/SL leg order IDs (from order.legs)
        - filled_at timestamp
        - Actual fill price (entry_fill_price)
        - Detects if position was closed externally (TP or SL filled)

        Args:
            position: The Position object to synchronize.

        Returns:
            Updated Position object with latest broker state.
        """
        if not position.alpaca_order_id:
            logger.warning(
                f"Cannot sync position {position.position_id}: no alpaca_order_id"
            )
            return position

        try:
            # Fetch parent order
            order = self.get_order_details(position.alpaca_order_id)
            if not order:
                position.failed_reason = "Parent order not found in Alpaca"
                return position

            # Check order status
            order_status = str(order.status).lower()

            if order_status == "filled":
                # Update fill details
                if order.filled_at:
                    position.filled_at = order.filled_at
                if order.filled_avg_price:
                    position.entry_fill_price = float(order.filled_avg_price)

                # Extract leg IDs from bracket order
                if hasattr(order, "legs") and order.legs:
                    for leg in order.legs:
                        leg_type = str(getattr(leg, "order_type", "")).lower()
                        leg_id = str(leg.id) if leg.id else None

                        if "limit" in leg_type:
                            # Take Profit is a limit order
                            position.tp_order_id = leg_id
                        elif "stop" in leg_type:
                            # Stop Loss is a stop order
                            position.sl_order_id = leg_id

                    logger.info(
                        f"Synced position {position.position_id}: "
                        f"TP={position.tp_order_id}, SL={position.sl_order_id}"
                    )

            elif order_status in ("canceled", "rejected", "expired"):
                position.failed_reason = (
                    f"Order {order_status}: {getattr(order, 'failed_message', 'Unknown')}"
                )
                position.status = TradeStatus.CLOSED

            # Check if TP or SL was filled (position closed externally)
            if position.tp_order_id:
                tp_order = self.get_order_details(position.tp_order_id)
                if tp_order and str(tp_order.status).lower() == "filled":
                    position.status = TradeStatus.CLOSED
                    logger.info(f"Position {position.position_id} closed via TP")

            if position.sl_order_id and position.status != TradeStatus.CLOSED:
                sl_order = self.get_order_details(position.sl_order_id)
                if sl_order and str(sl_order.status).lower() == "filled":
                    position.status = TradeStatus.CLOSED
                    logger.info(f"Position {position.position_id} closed via SL")

        except Exception as e:
            logger.error(f"Failed to sync position {position.position_id}: {e}")
            position.failed_reason = f"Sync error: {str(e)}"

        return position

    def modify_stop_loss(self, position: Position, new_stop: float) -> bool:
        """
        Update the stop-loss order for an open position.

        Uses PATCH /v2/orders/{sl_order_id} to replace the stop_price.

        Note: Cannot replace orders in pending states (pending_new,
        pending_cancel, pending_replace).

        Args:
            position: The Position with an active sl_order_id.
            new_stop: The new stop-loss price.

        Returns:
            True if replacement succeeded, False otherwise.
        """
        if not position.sl_order_id:
            logger.warning(
                f"Cannot modify stop for {position.position_id}: no sl_order_id"
            )
            return False

        try:
            # Check current SL order status first
            sl_order = self.get_order_details(position.sl_order_id)
            if not sl_order:
                logger.warning(f"SL order {position.sl_order_id} not found")
                return False

            sl_status = str(sl_order.status).lower()
            pending_states = {"pending_new", "pending_cancel", "pending_replace"}

            if sl_status in pending_states:
                logger.warning(f"Cannot replace SL order in {sl_status} state")
                return False

            if sl_status != "new" and sl_status != "accepted":
                logger.warning(f"SL order in non-replaceable state: {sl_status}")
                return False

            # Replace the stop-loss order
            from alpaca.trading.requests import ReplaceOrderRequest

            replace_request = ReplaceOrderRequest(stop_price=round(new_stop, 2))

            replaced_order = self.client.replace_order_by_id(
                order_id=position.sl_order_id, order_data=replace_request
            )

            logger.info(
                f"Modified SL for {position.position_id}: "
                f"{position.current_stop_loss} -> {new_stop}",
                extra={
                    "position_id": position.position_id,
                    "old_stop": position.current_stop_loss,
                    "new_stop": new_stop,
                    "new_order_id": str(replaced_order.id),
                },
            )

            # Update position with new SL order ID (replacement creates new order)
            position.sl_order_id = str(replaced_order.id)
            position.current_stop_loss = new_stop

            return True

        except Exception as e:
            logger.error(f"Failed to modify stop for {position.position_id}: {e}")
            return False

    def close_position_emergency(self, position: Position) -> bool:
        """
        Emergency close: Cancel all open orders and exit at market.

        Sequence:
        1. Cancel TP order if exists
        2. Cancel SL order if exists
        3. Submit market order to close the position

        Use for: Structural Invalidation, Manual Kill, System Shutdown.

        Args:
            position: The Position to close.

        Returns:
            True if all operations succeeded, False if any failed.
        """
        success = True

        # 1. Cancel TP order
        if position.tp_order_id:
            try:
                self.client.cancel_order_by_id(position.tp_order_id)
                logger.info(f"Canceled TP order {position.tp_order_id}")
            except Exception as e:
                # May already be filled or canceled
                logger.warning(f"Could not cancel TP order: {e}")
                success = False

        # 2. Cancel SL order
        if position.sl_order_id:
            try:
                self.client.cancel_order_by_id(position.sl_order_id)
                logger.info(f"Canceled SL order {position.sl_order_id}")
            except Exception as e:
                logger.warning(f"Could not cancel SL order: {e}")
                success = False

        # 3. Submit market order to close position
        try:
            # Determine close side (opposite of entry)
            close_side = (
                OrderSide.SELL if position.side == DomainOrderSide.BUY else OrderSide.BUY
            )

            close_request = MarketOrderRequest(
                symbol=position.signal_id.split("|")[-1]
                if "|" in position.signal_id
                else "BTC/USD",  # Fallback
                qty=position.qty,
                side=close_side,
                time_in_force=TimeInForce.GTC,
            )

            # Note: We need the symbol from somewhere - ideally from Position
            # For now, try to get from related signal via client_order_id
            try:
                parent_order = self.get_order_details(position.alpaca_order_id)
                if parent_order and parent_order.symbol:
                    close_request = MarketOrderRequest(
                        symbol=parent_order.symbol,
                        qty=position.qty,
                        side=close_side,
                        time_in_force=TimeInForce.GTC,
                    )
            except Exception:
                pass  # Use fallback

            close_order = self.client.submit_order(close_request)

            logger.info(
                f"EMERGENCY CLOSE: {position.position_id}",
                extra={
                    "position_id": position.position_id,
                    "close_order_id": str(close_order.id),
                    "qty": position.qty,
                    "side": close_side.value,
                },
            )

            position.status = TradeStatus.CLOSED

        except Exception as e:
            logger.error(f"Emergency close failed for {position.position_id}: {e}")
            position.failed_reason = f"Emergency close failed: {str(e)}"
            success = False

        return success
