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
from typing import Optional

from alpaca.trading.client import TradingClient
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

    def reconcile(self) -> ReconciliationReport:
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
                alpaca_result = self.alpaca.get_all_positions()
                alpaca_positions = (
                    alpaca_result if isinstance(alpaca_result, list) else []
                )
                alpaca_symbols = {p.symbol for p in alpaca_positions}
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
                    if pos:
                        # Mark as closed externally
                        pos.status = TradeStatus.CLOSED
                        pos.exit_reason = ExitReason.CLOSED_EXTERNALLY

                        # Update Firestore
                        self.position_repo.update_position(pos)
                        reconciled_count += 1

                        logger.warning(
                            f"Zombie healed: {symbol}",
                            extra={
                                "symbol": symbol,
                                "position_id": pos.position_id,
                                "status": "CLOSED_EXTERNALLY",
                            },
                        )

                        # Send Discord notification
                        try:
                            self.discord.send_message(
                                f"🧟 **ZOMBIE HEALED**: {symbol}\n"
                                f"Position was closed in Alpaca but marked OPEN in DB.\n"
                                f"Status updated to CLOSED_EXTERNALLY."
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to send Discord notification for zombie {symbol}: {e}"
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
