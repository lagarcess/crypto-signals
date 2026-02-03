"""State Reconciler Module (Issue #113).

Detects and resolves synchronization gaps between Alpaca broker state
and Firestore database state.

Example:
    >>> from crypto_signals.engine.reconciler import StateReconciler
    >>> from crypto_signals.market.data_provider import get_trading_client
    >>> from crypto_signals.repository.firestore import PositionRepository
    >>> from crypto_signals.notifications.discord import DiscordClient
    >>>
    >>> reconciler = StateReconciler(
    ...     alpaca_client=get_trading_client(),
    ...     position_repo=PositionRepository(),
    ...     discord_client=DiscordClient(),
    ... )
    >>> report = reconciler.reconcile()
    >>> if report.critical_issues:
    ...     print(f"Issues detected: {report.critical_issues}")
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.models import Position as AlpacaPosition
from alpaca.trading.requests import GetOrdersRequest
from crypto_signals.config import Settings, get_settings
from crypto_signals.domain.schemas import (
    ExitReason,
    ReconciliationReport,
    TradeStatus,
    TradeType,
)
from crypto_signals.notifications.discord import DiscordClient
from crypto_signals.repository.firestore import PositionRepository
from loguru import logger


class StateReconciler:
    """
    Detects and resolves synchronization gaps between Alpaca and Firestore.

    **Zombie Positions**: Firestore shows OPEN, but Alpaca shows closed
    (user closed manually, stop-loss filled, or partial fill).
    Resolution: Mark CLOSED_EXTERNALLY in Firestore.

    **Orphan Positions**: Alpaca shows OPEN, but Firestore has no record
    (manual trade placed, gap in system, or trade from another source).
    Resolution: Send critical Discord alert.

    Runs automatically at application startup before the main portfolio loop.
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
        1. Fetch all open positions from Alpaca (broker state)
        2. Fetch all open positions from Firestore (database state)
        3. Detect zombies: Firestore OPEN but Alpaca closed
        4. Detect orphans: Alpaca OPEN but Firestore missing
        5. Heal zombies: Mark CLOSED_EXTERNALLY in Firestore
        6. Alert orphans: Send critical Discord notification
        7. Return reconciliation report

        Args:
            min_age_minutes: Minimum age of position to be considered for zombie healing (race condition protection).

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

        zombies = []
        orphans = []
        reconciled_count = 0
        critical_issues = []

        try:
            # 1. Fetch Alpaca positions
            logger.info("Fetching positions from Alpaca...")
            try:
                # alpaca-py uses get_all_positions() to fetch all open positions
                raw_alpaca_positions = self.alpaca.get_all_positions()
                alpaca_positions_list: list[AlpacaPosition] = (
                    raw_alpaca_positions if isinstance(raw_alpaca_positions, list) else []
                )
                alpaca_symbols = {p.symbol for p in alpaca_positions_list}
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
            logger.info("Fetching positions from Firestore...")
            try:
                firestore_positions = self.position_repo.get_open_positions()

                # Filter out THEORETICAL trades (simulated state, not in Alpaca)
                # These would otherwise be detected as Zombies (Open in DB, Missing in Broker)
                firestore_positions = [
                    p
                    for p in firestore_positions
                    if p.trade_type != TradeType.THEORETICAL.value
                ]

                firestore_symbols = {p.symbol for p in firestore_positions}
                symbol_to_position = {p.symbol: p for p in firestore_positions}
                logger.info(
                    f"Firestore state: {len(firestore_symbols)} open positions",
                    extra={"symbols": sorted(list(firestore_symbols))},
                )
            except Exception as e:
                error_msg = f"Failed to fetch Firestore positions: {e}"
                logger.error(error_msg)
                critical_issues.append(error_msg)
                firestore_symbols = set()
                symbol_to_position = {}

            # 3. Detect discrepancies
            zombies = list(firestore_symbols - alpaca_symbols)
            orphans = list(alpaca_symbols - firestore_symbols)

            logger.info(
                "Reconciliation analysis complete",
                extra={
                    "zombies_detected": len(zombies),
                    "orphans_detected": len(orphans),
                },
            )

            # 4. Heal zombies
            for symbol in zombies:
                try:
                    pos = symbol_to_position.get(symbol)
                    if not pos:
                        continue

                    # ISSUE 244 FIX: Race Condition Protection
                    # Skip positions created recently (< min_age_minutes) as Alpaca might be syncing
                    if pos.created_at:
                        age = datetime.now(timezone.utc) - pos.created_at
                        if age < timedelta(minutes=min_age_minutes):
                            logger.warning(
                                f"Skipping young zombie candidate {symbol}",
                                extra={
                                    "symbol": symbol,
                                    "age_seconds": age.total_seconds(),
                                    "min_age_minutes": min_age_minutes,
                                },
                            )
                            continue

                    # ISSUE 244 FIX: Unused Verification Logic
                    # Verify exit via manual order history before closing
                    if self.handle_manual_exit_verification(pos):
                        # Verification successful - save the updated position
                        # pos.status/exit_reason already updated by handle_manual_exit_verification
                        self.position_repo.update_position(pos)
                        reconciled_count += 1

                        logger.warning(
                            f"Zombie healed: {symbol}",
                            extra={
                                "symbol": symbol,
                                "position_id": pos.position_id,
                                "status": pos.status,
                                "exit_reason": pos.exit_reason,
                            },
                        )
                        # Notification is sent by handle_manual_exit_verification
                    else:
                        # Verification failed - Critical Sync Issue
                        error_msg = (
                            f"CRITICAL SYNC ISSUE: {symbol} is OPEN in DB but MISSING in Alpaca. "
                            "No matching exit order found."
                        )
                        logger.critical(
                            error_msg,
                            extra={
                                "symbol": symbol,
                                "position_id": pos.position_id,
                            },
                        )
                        critical_issues.append(error_msg)

                        # Send critical alert for unverified zombie
                        try:
                            self.discord.send_message(
                                f"🛑 **CRITICAL SYNC FAILURE**: {symbol}\n"
                                f"Position is missing from Alpaca but **NO EXIT ORDER FOUND**.\n"
                                f"System will NOT close it automatically.\n"
                                f"**Action Required**: Investigate immediately."
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to send sync failure alert for {symbol}: {e}"
                            )

                except Exception as e:
                    error_msg = f"Failed to heal zombie {symbol}: {e}"
                    logger.error(error_msg)
                    critical_issues.append(error_msg)

            # 5. Alert orphans
            for symbol in orphans:
                logger.critical(
                    f"ORPHAN POSITION DETECTED: {symbol}",
                    extra={
                        "symbol": symbol,
                        "impact": "Position open in Alpaca but missing from DB",
                    },
                )

                try:
                    self.discord.send_message(
                        f"⚠️  **CRITICAL ORPHAN**: {symbol}\n"
                        f"Position is open in Alpaca but has no Firestore record.\n"
                        f"**Action Required**: Manual investigation and position management."
                    )
                except Exception as e:
                    logger.warning(f"Failed to send orphan alert for {symbol}: {e}")

                critical_issues.append(f"ORPHAN: {symbol}")

            # =====================================================================
            # ISSUE 139 FIX: Detect Reverse Orphans
            # Positions marked CLOSED in Firestore but still OPEN in Alpaca
            # This catches cases where exit orders were not properly submitted
            # =====================================================================
            logger.info("Checking for reverse orphans (CLOSED in DB, OPEN in Alpaca)...")
            try:
                closed_positions = self.position_repo.get_closed_positions(limit=50)
                reverse_orphans = []

                for closed_pos in closed_positions:
                    try:
                        # Check if this position is still open in Alpaca
                        alpaca_pos = self.alpaca.get_open_position(closed_pos.symbol)
                        if alpaca_pos:
                            # REVERSE ORPHAN DETECTED
                            reverse_orphans.append(closed_pos.symbol)
                            logger.critical(
                                f"REVERSE ORPHAN DETECTED: {closed_pos.symbol}",
                                extra={
                                    "symbol": closed_pos.symbol,
                                    "position_id": closed_pos.position_id,
                                    "impact": "Position closed in DB but STILL OPEN in Alpaca!",
                                },
                            )

                            try:
                                self.discord.send_message(
                                    f"🚨 **CRITICAL REVERSE ORPHAN**: {closed_pos.symbol}\n"
                                    f"Position is CLOSED in Firestore but STILL OPEN in Alpaca!\n"
                                    f"**Position ID**: {closed_pos.position_id}\n"
                                    f"**Action Required**: Manual close in Alpaca dashboard."
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to send reverse orphan alert for {closed_pos.symbol}: {e}"
                                )

                            critical_issues.append(f"REVERSE_ORPHAN: {closed_pos.symbol}")

                    except Exception as e:
                        # 404/not found = position is correctly closed in Alpaca
                        if "not found" not in str(e).lower() and "404" not in str(e):
                            logger.warning(
                                f"Error checking closed position {closed_pos.symbol}: {e}"
                            )

                if reverse_orphans:
                    logger.warning(
                        f"Found {len(reverse_orphans)} reverse orphans",
                        extra={"symbols": reverse_orphans},
                    )

            except Exception as e:
                logger.warning(f"Reverse orphan detection failed: {e}")

        except Exception as e:
            error_msg = f"Reconciliation execution failed: {e}"
            logger.error(error_msg)
            critical_issues.append(error_msg)

        # 6. Build report
        duration_seconds = time.time() - start_time

        report = ReconciliationReport(
            zombies=zombies,
            orphans=orphans,
            reconciled_count=reconciled_count,
            duration_seconds=duration_seconds,
            critical_issues=critical_issues,
        )

        # Log summary
        logger.info(
            "Reconciliation complete",
            extra={
                "zombies": len(report.zombies),
                "orphans": len(report.orphans),
                "reconciled": report.reconciled_count,
                "duration_seconds": round(report.duration_seconds, 3),
                "critical_issues": len(report.critical_issues),
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
            # Using specific check for Alpaca OrderSide enum to avoid domain mismatch
            from alpaca.trading.enums import OrderSide as AlpacaOrderSide
            from crypto_signals.domain.schemas import OrderSide as DomainOrderSide

            close_side = (
                AlpacaOrderSide.SELL
                if position.side == DomainOrderSide.BUY
                else AlpacaOrderSide.BUY
            )

            # 2. Search recent filled orders for this symbol

            from alpaca.trading.enums import QueryOrderStatus

            request = GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                symbols=[position.symbol],
                limit=500,
                side=close_side,
            )
            from alpaca.trading.models import Order

            recent_orders_result = self.alpaca.get_orders(filter=request)
            recent_orders = (
                recent_orders_result if isinstance(recent_orders_result, list) else []
            )

            # 3. Find the most recent fill that is NOT our known TP or SL legs
            closing_order = None
            ignored_ids = {position.tp_order_id, position.sl_order_id}

            for o in recent_orders:
                if isinstance(o, Order) and str(o.id) not in ignored_ids:
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
                        f"Position was found closed on Alpaca but open in DB.\n"
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
