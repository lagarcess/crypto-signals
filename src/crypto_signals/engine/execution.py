"""
Execution Engine for Alpaca Order Management.

This module bridges Signal objects to live Alpaca trades using Bracket Orders
for atomic Entry, Take-Profit, and Stop-Loss management.

Key Capabilities:
    - execute_signal(): Submit bracket orders with Entry, TP, and SL
    - sync_position_status(): Synchronize position with broker state
    - modify_stop_loss(): Trail stop-loss orders (for Chandelier Exits)
    - close_position_emergency(): Cancel all legs and exit at market
    - get_order_details(): Retrieve order for analytics enrichment
"""

from datetime import datetime, timezone
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
    ExitReason,
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
    Manages the complete order lifecycle from Signal to Alpaca trade.

    Uses Bracket Orders for atomic Entry, Take-Profit, and Stop-Loss.
    Supports position synchronization, stop-loss trailing, and emergency exits.

    Methods:
        execute_signal: Submit bracket order for a Signal
        get_order_details: Retrieve order by ID for enrichment
        sync_position_status: Sync position with Alpaca broker state
        modify_stop_loss: Replace stop-loss order (trailing)
        close_position_emergency: Cancel legs and exit at market
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

        # ENVIRONMENT GATE: Block execution in non-PROD environments
        if self.settings.ENVIRONMENT != "PROD":
            logger.info(
                f"[THEORETICAL MODE] Execution skipped for {signal.symbol} "
                f"(Environment: {self.settings.ENVIRONMENT})"
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
                account_id="paper",  # All trades use paper account; TEST_MODE only controls Discord routing
                symbol=signal.symbol,
                signal_id=signal.signal_id,
                alpaca_order_id=str(order.id),
                discord_thread_id=signal.discord_thread_id,
                status=TradeStatus.OPEN,
                entry_fill_price=signal.entry_price,
                current_stop_loss=signal.suggested_stop,
                qty=qty,
                side=effective_side,
                target_entry_price=signal.entry_price,
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
        # ENVIRONMENT GATE: Skip sync in non-PROD environments
        if self.settings.ENVIRONMENT != "PROD":
            return position

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

                # Calculate entry slippage
                if position.target_entry_price and position.target_entry_price > 0:
                    position.entry_slippage_pct = round(
                        (position.entry_fill_price - position.target_entry_price)
                        / position.target_entry_price
                        * 100,
                        4,
                    )

                # Extract commission if available (Alpaca reports fees in 'commission' field)
                # Handle None values (common in paper trading)
                if hasattr(order, "commission"):
                    position.commission = float(order.commission or 0.0)

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
            # Only check if leg IDs were successfully extracted to avoid unnecessary API calls
            if position.tp_order_id:
                tp_order = self.get_order_details(position.tp_order_id)
                if tp_order and str(tp_order.status).lower() == "filled":
                    position.status = TradeStatus.CLOSED
                    # Capture exit details for PnL calculation
                    if tp_order.filled_avg_price:
                        position.exit_fill_price = float(tp_order.filled_avg_price)
                    if tp_order.filled_at:
                        position.exit_time = tp_order.filled_at
                    position.exit_reason = ExitReason.TP_HIT
                    logger.info(f"Position {position.position_id} closed via TP")

            if position.sl_order_id and position.status != TradeStatus.CLOSED:
                sl_order = self.get_order_details(position.sl_order_id)
                if sl_order and str(sl_order.status).lower() == "filled":
                    position.status = TradeStatus.CLOSED
                    # Capture exit details for PnL calculation
                    if sl_order.filled_avg_price:
                        position.exit_fill_price = float(sl_order.filled_avg_price)
                    if sl_order.filled_at:
                        position.exit_time = sl_order.filled_at
                    position.exit_reason = ExitReason.STOP_LOSS
                    logger.info(f"Position {position.position_id} closed via SL")

            # -------------------------------------------------------------------------
            # CALCULATE EXIT METRICS (when position is closed)
            # -------------------------------------------------------------------------
            if position.status == TradeStatus.CLOSED:
                # Calculate trade duration
                if position.filled_at and position.exit_time:
                    duration = position.exit_time - position.filled_at
                    position.trade_duration_seconds = int(duration.total_seconds())

                # Calculate exit slippage (vs target stop or TP level)
                # High-fidelity: compare against expected exit price
                if position.exit_fill_price:
                    target_exit = None
                    if position.exit_reason == ExitReason.STOP_LOSS:
                        # For SL, target is the current stop loss price
                        target_exit = position.current_stop_loss
                    elif position.exit_reason == ExitReason.TP_HIT:
                        # For TP, slippage is typically zero (limit order)
                        # but we still track it for completeness
                        target_exit = position.exit_fill_price
                    else:
                        # Other exits (manual, emergency) - no expected target
                        target_exit = position.exit_fill_price

                    if target_exit and target_exit > 0:
                        position.exit_slippage_pct = round(
                            (position.exit_fill_price - target_exit) / target_exit * 100,
                            4,
                        )

                # Update realized PnL
                pnl_usd, pnl_pct = self._calculate_realized_pnl(position)
                position.realized_pnl_usd = pnl_usd
                position.realized_pnl_pct = pnl_pct

            # -------------------------------------------------------------------------
            # MANUAL / EXTERNAL EXIT DETECTION
            # -------------------------------------------------------------------------
            # If position is still marked OPEN but TP/SL were not triggered,
            # verify if the position corresponds to actual broker state.
            if position.status == TradeStatus.OPEN:
                try:
                    # Check actual open position on Alpaca
                    # get_open_position raises 404 if no position exists
                    self.client.get_open_position(position.symbol)
                except Exception as e:
                    # 404 means no position -> It was closed manually/externally
                    if "not found" in str(e).lower() or "404" in str(e):
                        logger.warning(
                            f"Position {position.position_id} not found on Alpaca (Manual Exit detected)"
                        )

                        # Find the closing order to get fill price
                        try:
                            # Search recent filled orders (opposite side)
                            close_side = (
                                OrderSide.SELL
                                if position.side == DomainOrderSide.BUY
                                else OrderSide.BUY
                            )

                            recent_orders = self.client.get_orders(
                                filter={
                                    "status": "filled",
                                    "symbols": [position.symbol],
                                    "limit": 5,
                                    "side": close_side,
                                }
                            )

                            # Find the most recent fill that is NOT our TP or SL
                            closing_order = None
                            ignored_ids = {position.tp_order_id, position.sl_order_id}

                            for o in recent_orders:
                                if str(o.id) not in ignored_ids:
                                    closing_order = o
                                    break

                            if closing_order:
                                position.status = TradeStatus.CLOSED
                                position.exit_reason = ExitReason.MANUAL_EXIT
                                if closing_order.filled_avg_price:
                                    position.exit_fill_price = float(
                                        closing_order.filled_avg_price
                                    )
                                if closing_order.filled_at:
                                    position.exit_time = closing_order.filled_at
                                logger.info(
                                    f"Detected MANUAL EXIT for {position.position_id} "
                                    f"at ${position.exit_fill_price}"
                                )
                            else:
                                # Closed but can't find order? Mark closed anyway to sync state
                                position.status = TradeStatus.CLOSED
                                position.exit_reason = ExitReason.MANUAL_EXIT
                                logger.warning(
                                    f"Could not find closing order for {position.position_id}. "
                                    "Marking CLOSED with unknown price."
                                )

                        except Exception as search_err:
                            logger.error(f"Failed to search closing order: {search_err}")
                            # Fallback close
                            position.status = TradeStatus.CLOSED
                            position.exit_reason = ExitReason.MANUAL_EXIT

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
        # ENVIRONMENT GATE: Skip modification in non-PROD environments
        if self.settings.ENVIRONMENT != "PROD":
            logger.info(
                f"[THEORETICAL MODE] Stop modification skipped for {position.position_id}"
            )
            return True  # Return True to simulate success in logic flow

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

    def scale_out_position(self, position: Position, scale_pct: float = 0.5) -> bool:
        """
        Partial close: Sell scale_pct of position at market.

        Used for TP1 automation - scale out 50% when first target is hit.

        1. Calculate scale-out quantity
        2. Submit market order to close portion
        3. Update position.qty with remaining
        4. Record scale-out details for PnL calculations

        Args:
            position: The Position with an active trade
            scale_pct: Percentage to close (default 0.5 = 50%)

        Returns:
            True if scale-out order submitted successfully
        """
        # ENVIRONMENT GATE: Skip scale-out in non-PROD environments
        if self.settings.ENVIRONMENT != "PROD":
            logger.info(
                f"[THEORETICAL MODE] Scale-out skipped for {position.position_id}"
            )
            return True  # Return True to simulate success

        if not position.qty or position.qty <= 0:
            logger.warning(f"Cannot scale out {position.position_id}: no quantity")
            return False

        try:
            # Capture original qty BEFORE any calculations (only on first scale-out)
            if position.original_qty is None:
                position.original_qty = position.qty

            # Calculate scale-out quantity
            scale_qty = position.qty * scale_pct

            # For crypto, qty can be fractional. Round to 8 decimal places.
            scale_qty = round(scale_qty, 8)

            if scale_qty <= 0:
                logger.warning(f"Scale-out qty too small for {position.position_id}")
                return False

            # Determine close side (opposite of entry)
            close_side = (
                OrderSide.SELL if position.side == DomainOrderSide.BUY else OrderSide.BUY
            )

            # Submit market order for partial close
            close_request = MarketOrderRequest(
                symbol=position.symbol,
                qty=scale_qty,
                side=close_side,
                time_in_force=TimeInForce.GTC,
            )

            close_order = self.client.submit_order(close_request)

            # Get fill price from order (if immediate fill)
            fill_price = None
            if hasattr(close_order, "filled_avg_price") and close_order.filled_avg_price:
                fill_price = float(close_order.filled_avg_price)

            # Record scale-out in position
            position.scaled_out_qty += scale_qty
            position.scaled_out_price = fill_price  # Most recent (backward compat)
            position.scaled_out_at = datetime.now(timezone.utc)

            # Track individual scale-out for multi-stage PnL
            if fill_price is not None:
                position.scaled_out_prices.append(
                    {
                        "qty": scale_qty,
                        "price": fill_price,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

            # Update remaining quantity
            position.qty = round(position.qty - scale_qty, 8)

            logger.info(
                f"SCALE OUT: {position.position_id} - {scale_pct * 100:.0f}%",
                extra={
                    "position_id": position.position_id,
                    "symbol": position.symbol,
                    "scale_qty": scale_qty,
                    "remaining_qty": position.qty,
                    "fill_price": fill_price,
                    "order_id": str(close_order.id),
                },
            )

            return True

        except Exception as e:
            logger.error(f"Scale-out failed for {position.position_id}: {e}")
            position.failed_reason = f"Scale-out failed: {str(e)}"
            return False

    def move_stop_to_breakeven(self, position: Position) -> bool:
        """
        Move stop-loss to entry price (breakeven).

        Used after TP1 scale-out to protect remaining position.

        Args:
            position: The Position with an active stop-loss order

        Returns:
            True if stop moved successfully
        """
        if not position.entry_fill_price:
            logger.warning(
                f"Cannot move to breakeven {position.position_id}: no entry price"
            )
            return False

        # Add small buffer for slippage (0.1% in favorable direction)
        # For longs: breakeven slightly above entry
        # For shorts: breakeven slightly below entry
        buffer_pct = 0.001  # 0.1%
        if position.side == DomainOrderSide.BUY:
            breakeven_price = position.entry_fill_price * (1 + buffer_pct)
        else:
            breakeven_price = position.entry_fill_price * (1 - buffer_pct)

        breakeven_price = round(breakeven_price, 2)

        # Use existing modify_stop_loss method
        success = self.modify_stop_loss(position, breakeven_price)

        if success:
            position.breakeven_applied = True
            logger.info(
                f"BREAKEVEN: {position.position_id} stop -> ${breakeven_price}",
                extra={
                    "position_id": position.position_id,
                    "entry_price": position.entry_fill_price,
                    "breakeven_price": breakeven_price,
                },
            )

        return success

    def _calculate_realized_pnl(self, position: Position) -> tuple[float, float]:
        """
        Calculate aggregate realized PnL including all scale-outs.

        This method computes PnL from:
        1. All scaled-out portions (TP1, TP2 hits)
        2. Final exit of remaining position (if closed)

        Args:
            position: The Position to calculate PnL for.

        Returns:
            Tuple of (pnl_usd, pnl_pct) rounded for display.
        """
        entry = position.entry_fill_price
        exit_price = position.exit_fill_price
        is_long = position.side == DomainOrderSide.BUY

        if entry is None or entry == 0:
            return (0.0, 0.0)

        # PnL from scaled-out portions
        scaled_pnl = 0.0
        for scale in position.scaled_out_prices:
            scale_qty = scale.get("qty", 0)
            scale_price = scale.get("price", entry)
            if is_long:
                scaled_pnl += (scale_price - entry) * scale_qty
            else:
                scaled_pnl += (entry - scale_price) * scale_qty

        # PnL from final exit (if position is closed)
        final_pnl = 0.0
        if exit_price is not None:
            remaining_qty = position.qty
            if is_long:
                final_pnl = (exit_price - entry) * remaining_qty
            else:
                final_pnl = (entry - exit_price) * remaining_qty

        pnl_usd = scaled_pnl + final_pnl

        # Calculate percentage based on total position value
        total_qty = position.original_qty or (position.qty + position.scaled_out_qty)
        if total_qty > 0:
            pnl_pct = (pnl_usd / (entry * total_qty)) * 100
        else:
            pnl_pct = 0.0

        return (round(pnl_usd, 2), round(pnl_pct, 4))

    def close_position_emergency(self, position: Position) -> bool:
        """
        Emergency close: Cancel all open orders and exit at market.

        Sequence:
        1. Cancel TP order if exists (best effort - may already be filled)
        2. Cancel SL order if exists (best effort - may already be filled)
        3. Submit market order to close the position

        Use for: Structural Invalidation, Manual Kill, System Shutdown.

        Args:
            position: The Position to close.

        Returns:
            True if market order was submitted successfully, False otherwise.
            Note: Cancellation failures are logged but don't affect return value
            since orders may already be filled/canceled.
        """
        # ENVIRONMENT GATE: Skip emergency close in non-PROD environments
        if self.settings.ENVIRONMENT != "PROD":
            logger.info(
                f"[THEORETICAL MODE] Emergency close skipped for {position.position_id}"
            )
            return True

        # 1. Cancel TP order (best effort - may already be filled/canceled)
        if position.tp_order_id:
            try:
                self.client.cancel_order_by_id(position.tp_order_id)
                logger.info(f"Canceled TP order {position.tp_order_id}")
            except Exception as e:
                # Not an error - order may already be filled or canceled
                logger.debug(f"Could not cancel TP order (may be filled): {e}")

        # 2. Cancel SL order (best effort - may already be filled/canceled)
        if position.sl_order_id:
            try:
                self.client.cancel_order_by_id(position.sl_order_id)
                logger.info(f"Canceled SL order {position.sl_order_id}")
            except Exception as e:
                # Not an error - order may already be filled or canceled
                logger.debug(f"Could not cancel SL order (may be filled): {e}")

        # 3. Submit market order to close position
        try:
            # Determine close side (opposite of entry)
            close_side = (
                OrderSide.SELL if position.side == DomainOrderSide.BUY else OrderSide.BUY
            )

            # Use position.symbol directly (added to Position model for this purpose)
            close_request = MarketOrderRequest(
                symbol=position.symbol,
                qty=position.qty,
                side=close_side,
                time_in_force=TimeInForce.GTC,
            )

            close_order = self.client.submit_order(close_request)

            logger.info(
                f"EMERGENCY CLOSE: {position.position_id}",
                extra={
                    "position_id": position.position_id,
                    "symbol": position.symbol,
                    "close_order_id": str(close_order.id),
                    "qty": position.qty,
                    "side": close_side.value,
                },
            )

            position.status = TradeStatus.CLOSED
            return True

        except Exception as e:
            logger.error(f"Emergency close failed for {position.position_id}: {e}")
            position.failed_reason = f"Emergency close failed: {str(e)}"
            return False
