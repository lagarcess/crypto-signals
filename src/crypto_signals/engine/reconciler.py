"""State Reconciler Module (Issue #113).

Detects and resolves synchronization gaps between Alpaca broker state
and Firestore database state.

Example:
    >>> from crypto_signals.engine.reconciler import StateReconciler
    >>> from crypto_signals.market.data_provider import get_trading_client
    >>> from crypto_signals.repository.firestore import PositionRepository
    >>> from crypto_signals.notifications.discord import DiscordClient
    >>>
    >>> reconciler = StateReconciler(get_trading_client(), PositionRepository(), DiscordClient())
    >>> report = reconciler.reconcile()
    >>> if report.critical_issues:
    ...     print(f"Issues detected: {report.critical_issues}")
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.models import Position as AlpacaPosition
from alpaca.trading.requests import GetOrdersRequest
from crypto_signals.config import Settings, get_settings
from crypto_signals.domain.schemas import (
    ExitReason,
    ReconciliationReport,
    TradeStatus,
    TradeType,
)
from crypto_signals.domain.schemas import (
    OrderSide as DomainOrderSide,
)
from crypto_signals.notifications.discord import DiscordClient
from crypto_signals.repository.firestore import PositionRepository
from crypto_signals.utils.symbols import normalize_alpaca_symbol
from loguru import logger


class StateReconciler:
    """
    Detects and resolves synchronization gaps between Alpaca and Firestore.
    Handles Zombie Positions (Firestore OPEN, Alpaca CLOSED) and Orphans (Alpaca OPEN, Firestore MISSING).
    """

    def __init__(
        self,
        alpaca_client: TradingClient,
        position_repo: PositionRepository,
        discord_client: DiscordClient,
        settings: Optional[Settings] = None,
    ):
        """
        Initialize the StateReconciler.

        Args:
            alpaca_client: TradingClient for fetching broker positions.
            position_repo: PositionRepository for database operations.
            discord_client: DiscordClient for notifications.
            settings: Settings object (defaults to get_settings()).
        """
        self.alpaca = alpaca_client
        self.position_repo = position_repo
        self.discord = discord_client
        self.settings: Settings = settings or get_settings()

        logger.info(
            "StateReconciler initialized",
            extra={
                "environment": self.settings.ENVIRONMENT,
                "mode": "ENABLED" if self.settings.ENVIRONMENT == "PROD" else "DISABLED",
            },
        )

    def reconcile(self, min_age_minutes: int = 5) -> ReconciliationReport:
        """
        Execute full reconciliation between Alpaca and Firestore.

        Process:
        1. Fetch open positions from Alpaca and Firestore.
        2. Detect discrepancies (Zombies and Orphans).
        3. Heal zombies (verify exit then close in DB).
        4. Alert on orphans.

        Args:
            min_age_minutes: Min age to consider for zombie healing (race condition guard).

        Returns:
            ReconciliationReport: Summary of reconciliation results
        """
        start_time = time.time()

        # ENVIRONMENT GATE: Skip execution in non-PROD
        if self.settings.ENVIRONMENT != "PROD":
            logger.warning(
                f"Reconciliation skipped: ENVIRONMENT is {self.settings.ENVIRONMENT}, not PROD"
            )
            return ReconciliationReport(
                critical_issues=[
                    f"Reconciliation disabled in {self.settings.ENVIRONMENT}"
                ]
            )

        critical_issues = []
        healed_zombies = []
        detected_orphans = []

        try:
            # 1. Fetch Alpaca positions
            try:
                raw_alpaca_positions = self.alpaca.get_all_positions()
                alpaca_positions_list: list[AlpacaPosition] = (
                    raw_alpaca_positions if isinstance(raw_alpaca_positions, list) else []
                )
                # Normalize symbols for set comparison (e.g., AAVEUSD)
                alpaca_symbols = {
                    normalize_alpaca_symbol(p.symbol) for p in alpaca_positions_list
                }
                logger.info(
                    f"Alpaca state: {len(alpaca_symbols)} open positions",
                    extra={"symbols": sorted(list(alpaca_symbols))},
                )
            except Exception as e:
                error_msg = f"Failed to fetch Alpaca positions: {e}"
                logger.error(error_msg)
                critical_issues.append(error_msg)
                alpaca_symbols = set()

            # 2. Fetch Firestore positions
            try:
                # Get all positions with status OPEN
                firestore_positions = self.position_repo.get_open_positions()

                # Filter out THEORETICAL trades (simulations) as they don't exist in Alpaca
                firestore_positions = [
                    p
                    for p in firestore_positions
                    if p.trade_type != TradeType.THEORETICAL.value
                ]

                # Normalize symbols for comparison (e.g., AAVE/USD -> AAVEUSD)
                firestore_symbols_norm = {
                    normalize_alpaca_symbol(p.symbol) for p in firestore_positions
                }
                # Mapping from normalized back to original for lookup
                norm_to_original = {
                    normalize_alpaca_symbol(p.symbol): p.symbol
                    for p in firestore_positions
                }
                symbol_to_position = {p.symbol: p for p in firestore_positions}

                logger.info(
                    f"Firestore state: {len(firestore_symbols_norm)} open positions",
                    extra={"symbols": sorted(list(firestore_symbols_norm))},
                )
            except Exception as e:
                error_msg = f"Failed to fetch Firestore positions: {e}"
                logger.error(error_msg)
                critical_issues.append(error_msg)
                firestore_symbols_norm = set()
                norm_to_original = {}
                symbol_to_position = {}

            # 3. Detect discrepancies
            zombie_symbols_norm = firestore_symbols_norm - alpaca_symbols
            orphan_symbols_norm = alpaca_symbols - firestore_symbols_norm

            # Map zombies back to their original "slashed" symbols for DB lookup
            zombies = [norm_to_original[s] for s in zombie_symbols_norm]

            # Denormalize orphans for display consistency (BTCUSD -> BTC/USD)
            # Use configured symbols as the authority for formatting
            crypto_config = self.settings.CRYPTO_SYMBOLS or []
            config_map = {normalize_alpaca_symbol(s): s for s in crypto_config}

            orphans = []
            for s_norm in orphan_symbols_norm:
                if s_norm in config_map:
                    orphans.append(config_map[s_norm])
                else:
                    # Fallback to normalized if not in config (e.g. manual trade on new asset)
                    orphans.append(s_norm)

            logger.info(
                "Reconciliation analysis complete",
                extra={
                    "zombies_detected": len(zombies),
                    "orphans_detected": len(orphans),
                },
            )

            # 4. Process Zombies (Heal Firestore)
            for symbol in zombies:
                position = symbol_to_position.get(symbol)
                if not position:
                    continue

                # Race Condition Protection: Skip healing for young positions.
                # If a position was opened < X min ago, it might not be visible in
                # Alpaca's get_all_positions() yet due to eventual consistency.
                if position.created_at:
                    age = datetime.now(timezone.utc) - position.created_at
                    if age < timedelta(minutes=min_age_minutes):
                        logger.warning(
                            f"Skipping zombie healing for young position {symbol}",
                            extra={
                                "age_seconds": age.total_seconds(),
                                "min_age_minutes": min_age_minutes,
                            },
                        )
                        continue

                # Positive Verification Strategy:
                # Before closing in DB, try to find the matching manual exit order.
                if self.handle_manual_exit_verification(position):
                    self.position_repo.update_position(position)
                    healed_zombies.append(symbol)
                else:
                    # Verification failed: No exit order found.
                    # This is a critical gap (DB thinks OPEN, Broker has 0 qty, but NO exit order)
                    error_msg = (
                        f"ZOMBIE_EXIT_GAP: {symbol} has 0 qty on Alpaca, but NO closing order was found. "
                        "Manual investigation required."
                    )
                    critical_issues.append(error_msg)
                    try:
                        self.discord.send_message(f"🚨 **{error_msg}**")
                    except Exception as e:
                        logger.error(f"Failed to send zombie alert to Discord: {e}")

            # 5. Process Orphans (Alert Only)
            for symbol in orphans:
                # Orphans (Open in Alpaca, Missing in Firestore) require manual investigation.
                # Auto-creating them in Firestore is too risky as we don't have signal metadata.
                detected_orphans.append(symbol)
                error_msg = f"ORPHAN_POSITION: {symbol} is OPEN in Alpaca but missing from Firestore OPEN list."
                logger.error(error_msg)
                critical_issues.append(error_msg)
                try:
                    self.discord.send_message(f"🚨 **{error_msg}**")
                except Exception as e:
                    logger.error(f"Failed to send orphan alert to Discord: {e}")

        except Exception as e:
            critical_issues.append(f"Reconciliation loop crashed: {e}")
            logger.exception("Reconciliation crash")

        # 6. Check for Reverse Orphans (CLOSED in DB but OPEN in Alpaca)
        # This catch-all ensures that even if we closed something erroneously, we find it.
        try:
            # Re-fetch Firestore positions that were closed in the last 24 hours
            # This is a safety check.
            from crypto_signals.domain.schemas import TradeStatus

            closed_positions = self.position_repo.get_positions_by_status_and_time(
                status=TradeStatus.CLOSED, hours_lookback=24
            )
            reverse_orphans = []
            if closed_positions:
                for closed_pos in closed_positions:
                    try:
                        # Check if this position is still open in Alpaca
                        alpaca_pos = self.alpaca.get_open_position(
                            normalize_alpaca_symbol(closed_pos.symbol)
                        )
                        if alpaca_pos:
                            # REVERSE ORPHAN DETECTED
                            reverse_orphans.append(closed_pos.symbol)
                            msg = f"REVERSE_ORPHAN: {closed_pos.symbol} is CLOSED in DB but still OPEN in Alpaca!"
                            logger.error(msg)
                            critical_issues.append(msg)
                    except Exception as e:
                        if "not found" in str(e).lower() or "404" in str(e):
                            continue
                        else:
                            logger.warning(
                                f"Error checking reverse orphan for {closed_pos.symbol}: {e}"
                            )

        except Exception as e:
            logger.warning(f"Reverse orphan check failed: {e}")

        # Summary
        duration = time.time() - start_time
        report = ReconciliationReport(
            critical_issues=critical_issues,
            zombies=zombies,
            orphans=orphans,
            reconciled_count=len(healed_zombies),
            duration_seconds=round(duration, 2),
        )

        logger.info(
            "Reconciliation finished",
            extra={
                "duration": report.duration_seconds,
                "healed": len(healed_zombies),
                "orphans": len(orphans),
                "errors": len(critical_issues),
            },
        )

        return report

    def handle_manual_exit_verification(self, position) -> bool:
        """
        Verify if a position that is missing from Alpaca has a corresponding manual exit order.
        If verified, it updates the position object and returns True.

        This logic is centralized here to unify state reconciliation strategies.
        """
        logger.warning(
            f"Position {position.position_id} ({position.symbol}) not found on Alpaca. "
            "Verifying manual exit via order history..."
        )

        try:
            # 1. Determine the expected exit side
            close_side = (
                AlpacaOrderSide.SELL
                if position.side == DomainOrderSide.BUY
                else AlpacaOrderSide.BUY
            )

            # 2. Search recent filled orders for this symbol
            request = GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                symbols=[normalize_alpaca_symbol(position.symbol)],
                limit=500,
                side=close_side,
            )

            recent_orders_result = self.alpaca.get_orders(filter=request)
            recent_orders = (
                recent_orders_result if isinstance(recent_orders_result, list) else []
            )

            # 3. Find the most recent fill that is NOT our known TP or SL legs
            closing_order = None
            ignored_ids = {
                position.tp_order_id,
                position.sl_order_id,
                position.alpaca_order_id,
                position.position_id,  # Used as client_order_id for entry
            }

            for o in recent_orders:
                # Duck-typing check to handle both SDK objects and mocks in tests
                o_id = str(getattr(o, "id", None))
                client_id = (
                    str(getattr(o, "client_order_id", None))
                    if getattr(o, "client_order_id", None)
                    else None
                )

                if o_id in ignored_ids or (client_id and client_id in ignored_ids):
                    continue

                closing_order = o
                break

            # 4. If closing order found, heal the position state
            if closing_order:
                position.status = TradeStatus.CLOSED
                position.exit_reason = ExitReason.MANUAL_EXIT
                if closing_order.filled_avg_price:
                    position.exit_fill_price = float(closing_order.filled_avg_price)
                if closing_order.filled_at:
                    position.exit_time = closing_order.filled_at
                position.exit_order_id = str(closing_order.id)

                logger.info(
                    f"✅ MANUAL EXIT VERIFIED: {position.symbol} via Order {closing_order.id}",
                    extra={
                        "symbol": position.symbol,
                        "order_id": closing_order.id,
                        "price": position.exit_fill_price,
                    },
                )

                # Notify Discord of the manual exit detected during sync
                try:
                    self.discord.send_message(
                        f"☝️  **MANUAL EXIT DETECTED**: {position.symbol}\n"
                        f"Position was found closed on Alpaca but open in DB.\\n"
                        f"Verified via manually placed order: `{closing_order.id}`."
                    )
                except Exception as notify_err:
                    logger.warning(
                        f"Failed to notify manual exit for {position.symbol}: {notify_err}"
                    )

                return True

            # 5. If NO closing order found, it's a critical sync issue (don't close yet)
            logger.error(
                f"🛑 EXIT VERIFICATION FAILED: {position.symbol} missing from Alpaca "
                "but NO matching closing order found. Keeping open in DB to prevent gap."
            )
            return False

        except Exception as e:
            logger.error(
                f"Error during manual exit verification for {position.symbol}: {e}"
            )
            return False
