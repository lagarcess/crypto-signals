"""
Main Application Entrypoint.

This script executes the signal generation pipeline for a defined portfolio of assets.
It orchestrates data fetching, pattern recognition, persistence, and notifications.
"""

import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from loguru import logger

from crypto_signals.config import (
    get_crypto_data_client,
    get_settings,
    get_stock_data_client,
    get_trading_client,
    load_config_from_firestore,
)
from crypto_signals.domain.schemas import (
    AssetClass,
    ExitReason,
    OrderSide,
    SignalStatus,
    TradeStatus,
)
from crypto_signals.engine.execution import ExecutionEngine
from crypto_signals.engine.signal_generator import SignalGenerator
from crypto_signals.market.asset_service import AssetValidationService
from crypto_signals.market.data_provider import MarketDataProvider
from crypto_signals.notifications.discord import DiscordClient
from crypto_signals.observability import (
    configure_logging,
    console,
    create_execution_summary_table,
    create_portfolio_progress,
    get_metrics_collector,
    log_execution_time,
    setup_gcp_logging,
)
from crypto_signals.repository.firestore import PositionRepository, SignalRepository
from crypto_signals.secrets_manager import init_secrets

# Configure logging with Rich integration
configure_logging(level="INFO")


# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_requested = True


def main():
    """Execute the main signal generation loop."""
    global shutdown_requested

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Get metrics collector
    metrics = get_metrics_collector()

    # Get settings early for GCP logging setup
    settings = get_settings()

    # Enable GCP Cloud Logging if configured (additive - does not disable Rich output)
    # This is inside main() to allow graceful error handling if credentials are missing
    if settings.ENABLE_GCP_LOGGING:
        try:
            setup_gcp_logging()
        except Exception as e:
            logger.warning(
                f"Failed to initialize GCP Cloud Logging: {e}. "
                "Continuing with Rich terminal logging only."
            )

    logger.info("Starting Crypto Sentinel Signal Generator...")
    app_start_time = time.time()

    try:
        # Initialize Secrets
        logger.info("Loading secrets...")
        with log_execution_time(logger, "load_secrets"):
            if not init_secrets():
                logger.critical("Failed to load required secrets. Exiting.")
                sys.exit(1)

            # Initialize Services
            logger.info("Initializing services...")
            with log_execution_time(logger, "initialize_services"):
                stock_client = get_stock_data_client()
                crypto_client = get_crypto_data_client()
                market_provider = MarketDataProvider(stock_client, crypto_client)
                generator = SignalGenerator(market_provider=market_provider)
                repo = SignalRepository()
                position_repo = PositionRepository()
                discord = DiscordClient()
                asset_validator = AssetValidationService(get_trading_client())
                execution_engine = ExecutionEngine()

        # Define Portfolio
        firestore_config = load_config_from_firestore()

        if firestore_config:
            logger.info("Using configuration from Firestore (overriding .env)")
            if "CRYPTO_SYMBOLS" in firestore_config:
                settings.CRYPTO_SYMBOLS = firestore_config["CRYPTO_SYMBOLS"]
        else:
            logger.info("Using configuration from .env")

        # Pre-flight: Validate symbols against Alpaca's live asset status
        logger.info("Validating portfolio assets...")
        with log_execution_time(logger, "asset_validation"):
            valid_crypto = asset_validator.get_valid_portfolio(
                settings.CRYPTO_SYMBOLS, AssetClass.CRYPTO
            )
            valid_equity = asset_validator.get_valid_portfolio(
                settings.EQUITY_SYMBOLS, AssetClass.EQUITY
            )

        portfolio_items = [(s, AssetClass.CRYPTO) for s in valid_crypto] + [
            (s, AssetClass.EQUITY) for s in valid_equity
        ]

        if not portfolio_items:
            logger.warning(
                "No valid symbols to process! All configured symbols were filtered out "
                "during asset validation. Check the 'INACTIVE ASSET SKIPPED' panels above."
            )

        logger.info(f"Processing {len(portfolio_items)} symbols...")

        # Rate limiting (Alpaca: 200 req/min = 0.3s minimum, use 0.5s for safety)
        rate_limit_delay = getattr(settings, "RATE_LIMIT_DELAY", 0.5)

        # Execution Loop with Rich Progress Bar
        signals_found = 0
        symbols_processed = 0
        errors_encountered = 0

        with create_portfolio_progress(len(portfolio_items)) as (progress, task):
            for idx, (symbol, asset_class) in enumerate(portfolio_items):
                # Update progress bar description
                progress.update(
                    task, description=f"[cyan]Analyzing {symbol} ({asset_class.value})..."
                )

                # Check for shutdown signal
                if shutdown_requested:
                    logger.info("Shutdown requested. Stopping processing gracefully...")
                    break

                symbol_start_time = time.time()

                try:
                    # Rate limiting: Add delay between symbols (except first)
                    if idx > 0:
                        logger.debug(f"Rate limit delay: {rate_limit_delay}s")
                        time.sleep(rate_limit_delay)

                    logger.info(
                        f"Analyzing {symbol} ({asset_class.value})...",
                        extra={"symbol": symbol, "asset_class": asset_class.value},
                    )

                    # Fetch Data ONCE
                    try:
                        df = market_provider.get_daily_bars(
                            symbol, asset_class, lookback_days=365
                        )
                    except Exception as e:
                        logger.error(f"Failed to fetch data for {symbol}: {e}")
                        continue

                    if df.empty:
                        logger.warning(f"No data for {symbol}")
                        continue

                    # Generate Signals
                    trade_signal = generator.generate_signals(
                        symbol, asset_class, dataframe=df
                    )

                    # Track metrics
                    symbol_duration = time.time() - symbol_start_time
                    symbols_processed += 1

                    if trade_signal:
                        signals_found += 1
                        logger.info(
                            f"SIGNAL FOUND: {trade_signal.pattern_name} "
                            f"on {trade_signal.symbol}",
                            extra={
                                "symbol": trade_signal.symbol,
                                "pattern": trade_signal.pattern_name,
                                "stop_loss": trade_signal.suggested_stop,
                            },
                        )

                        # Notify Discord FIRST to capture thread_id for lifecycle updates
                        thread_id = discord.send_signal(trade_signal)
                        if thread_id:
                            # Attach thread_id to signal for lifecycle updates
                            trade_signal.discord_thread_id = thread_id
                            logger.info(
                                "Thread ID captured for signal lifecycle tracking",
                                extra={
                                    "signal_id": trade_signal.signal_id,
                                    "symbol": trade_signal.symbol,
                                    "thread_id": thread_id,
                                },
                            )
                        else:
                            logger.warning(
                                "Failed to send Discord notification for "
                                f"{trade_signal.symbol}",
                                extra={"symbol": trade_signal.symbol},
                            )

                        # Persist signal
                        persistence_start = time.time()
                        try:
                            repo.save(trade_signal)
                            persistence_duration = time.time() - persistence_start
                            logger.info(
                                f"Signal {trade_signal.signal_id} persisted to Firestore",
                                extra={
                                    "signal_id": trade_signal.signal_id,
                                    "symbol": trade_signal.symbol,
                                    "thread_id": getattr(
                                        trade_signal, "discord_thread_id", None
                                    ),
                                    "duration_seconds": round(persistence_duration, 3),
                                },
                            )
                            metrics.record_success(
                                "signal_persistence", persistence_duration
                            )
                        except Exception as e:
                            persistence_duration = time.time() - persistence_start
                            logger.error(
                                f"Failed to persist signal {trade_signal.signal_id} to Firestore: {e}",
                                extra={
                                    "signal_id": trade_signal.signal_id,
                                    "symbol": trade_signal.symbol,
                                    "thread_id": getattr(
                                        trade_signal, "discord_thread_id", None
                                    ),
                                    "error": str(e),
                                },
                            )
                            metrics.record_failure(
                                "signal_persistence", persistence_duration
                            )
                            # Note: We intentionally do NOT re-raise here.
                            # Signal generation succeeded - only persistence failed.
                            # The failure is already logged and metrics recorded above.

                        # Execute trade if execution is enabled
                        # Safety: ExecutionEngine has built-in guards for:
                        #   1. ALPACA_PAPER_TRADING must be True
                        #   2. ENABLE_EXECUTION must be True
                        if settings.ENABLE_EXECUTION:
                            execution_start = time.time()
                            try:
                                position = execution_engine.execute_signal(trade_signal)
                                execution_duration = time.time() - execution_start
                                if position:
                                    logger.info(
                                        f"ORDER EXECUTED: {trade_signal.symbol}",
                                        extra={
                                            "signal_id": trade_signal.signal_id,
                                            "symbol": trade_signal.symbol,
                                            "position_id": position.position_id,
                                            "qty": position.qty,
                                            "duration_seconds": round(
                                                execution_duration, 3
                                            ),
                                        },
                                    )
                                    metrics.record_success(
                                        "order_execution", execution_duration
                                    )
                                else:
                                    # Execution was blocked by safety guards
                                    logger.debug(
                                        f"Execution skipped for {trade_signal.symbol} "
                                        "(blocked by safety guards or validation)"
                                    )
                            except Exception as e:
                                execution_duration = time.time() - execution_start
                                logger.error(
                                    f"Failed to execute order for {trade_signal.symbol}: {e}",
                                    extra={
                                        "signal_id": trade_signal.signal_id,
                                        "symbol": trade_signal.symbol,
                                        "error": str(e),
                                    },
                                )
                                metrics.record_failure(
                                    "order_execution", execution_duration
                                )

                        metrics.record_success("signal_generation", symbol_duration)
                    else:
                        logger.debug(f"No signal for {symbol}.")
                        metrics.record_success("signal_generation", symbol_duration)

                    # Active Trade Validation
                    # Check for updates on existing WAITING/ACTIVE signals
                    active_signals = repo.get_active_signals(symbol)
                    if active_signals:
                        logger.info(
                            f"Checking active signals for {symbol} ({len(active_signals)})..."
                        )

                        # 1. Run Expiration Check (24h Rule)
                        now_utc = datetime.now(timezone.utc)
                        today_date = now_utc.date()

                        # Check exits first
                        exited_signals = generator.check_exits(
                            active_signals, symbol, asset_class, dataframe=df
                        )

                        # Process Exits (TP / Invalidation) and Trail Updates
                        for exited in exited_signals:
                            # --- TRAIL UPDATE (not a status change) ---
                            if getattr(exited, "_trail_updated", False):
                                # Calculate movement percentage (absolute for Short positions)
                                old_tp3 = getattr(exited, "_previous_tp3", 0.0)
                                new_tp3 = exited.take_profit_3 or 0.0
                                movement_pct = (
                                    abs((new_tp3 - old_tp3) / old_tp3 * 100)
                                    if old_tp3 > 0
                                    else 100.0
                                )

                                logger.info(
                                    f"TRAIL UPDATE: {exited.signal_id} "
                                    f"TP3 moved from ${old_tp3:.2f} to ${new_tp3:.2f} "
                                    f"({movement_pct:.1f}%)",
                                    extra={
                                        "symbol": symbol,
                                        "signal_id": exited.signal_id,
                                        "old_tp3": old_tp3,
                                        "new_tp3": new_tp3,
                                        "movement_pct": movement_pct,
                                    },
                                )

                                # Always persist the updated trailing value
                                repo.update_signal(exited)

                                # Notify Discord if significant movement (>1%)
                                if movement_pct > 1.0:
                                    discord.send_trail_update(
                                        exited,
                                        old_stop=old_tp3,
                                        asset_class=asset_class,
                                    )

                                # === SYNC TRAIL TO ALPACA ===
                                # Update broker stop-loss to match new trailing stop
                                if settings.ENABLE_EXECUTION and new_tp3:
                                    positions = position_repo.get_by_signal_id(
                                        exited.signal_id
                                    )
                                    for pos in positions:
                                        if pos.status == TradeStatus.OPEN:
                                            if execution_engine.modify_stop_loss(
                                                pos, new_tp3
                                            ):
                                                logger.info(
                                                    f"TRAIL SYNC: Stop -> "
                                                    f"${new_tp3:.2f} for "
                                                    f"{pos.position_id}"
                                                )
                                                position_repo.update_position(pos)

                                # Clean up private attributes
                                if hasattr(exited, "_trail_updated"):
                                    delattr(exited, "_trail_updated")
                                if hasattr(exited, "_previous_tp3"):
                                    delattr(exited, "_previous_tp3")

                                # Remove from active_signals to skip expiration check
                                if exited in active_signals:
                                    active_signals.remove(exited)
                                continue

                            # --- STATUS CHANGE (Exit) ---
                            logger.info(
                                f"SIGNAL UPDATE: {exited.signal_id} "
                                f"status -> {exited.status}",
                                extra={
                                    "symbol": symbol,
                                    "signal_id": exited.signal_id,
                                    "new_status": exited.status,
                                },
                            )
                            repo.update_signal(exited)

                            # Notify Discord of Status Change
                            # Uses send_signal_update for consistent formatting
                            # (TEST/LIVE mode labels, pattern name formatting, etc.)
                            if not exited.discord_thread_id:
                                # Self-healing: Orphaned signal - send recovery msg
                                logger.info(
                                    f"Self-healing: Orphaned signal {exited.signal_id} - "
                                    "sending update to main channel"
                                )
                                # For orphaned signals, prepend recovery notice
                                recovery_prefix = (
                                    f"🔄 **THREAD RECOVERY: {symbol}** 🔄\n"
                                    f"*(Original thread unavailable)*\n\n"
                                )
                                # Build inline message for recovery case
                                status_emoji = {
                                    SignalStatus.INVALIDATED: "🚫",
                                    SignalStatus.TP1_HIT: "🎯",
                                    SignalStatus.TP2_HIT: "🚀",
                                    SignalStatus.TP3_HIT: "🌕",
                                    SignalStatus.EXPIRED: "⏳",
                                }.get(exited.status, "ℹ️")
                                msg = (
                                    f"{status_emoji} **SIGNAL UPDATE: {symbol}** "
                                    f"{status_emoji}\n"
                                    f"**Status**: {exited.status.value}\n"
                                    f"**Pattern**: {exited.pattern_name}\n"
                                )
                                if exited.exit_reason:
                                    msg += f"**Reason**: {exited.exit_reason}\n"
                                if exited.status == SignalStatus.TP1_HIT:
                                    msg += (
                                        "ℹ️ **Action**: Scaling Out (50%) "
                                        "& Stop -> **Breakeven**"
                                    )
                                discord.send_message(
                                    recovery_prefix + msg, asset_class=asset_class
                                )
                            else:
                                # Normal case: use dedicated method
                                discord.send_signal_update(
                                    exited, asset_class=asset_class
                                )

                            # === TP AUTOMATION ===
                            # Progressive stop management on each TP stage
                            if settings.ENABLE_EXECUTION:
                                # Find position linked to this signal
                                positions = position_repo.get_by_signal_id(
                                    exited.signal_id
                                )
                                for pos in positions:
                                    if pos.status != TradeStatus.OPEN:
                                        continue

                                    # TP1: Scale out 50% + move stop to breakeven
                                    if exited.status == SignalStatus.TP1_HIT:
                                        # Idempotency: Skip if already scaled (restarts/retries)
                                        if pos.scaled_out_qty > 0:
                                            logger.debug(
                                                f"TP1 already processed for {pos.position_id}, "
                                                f"scaled_out_qty={pos.scaled_out_qty}"
                                            )
                                        else:
                                            # 1. Scale out 50%
                                            if execution_engine.scale_out_position(
                                                pos, 0.5
                                            ):
                                                logger.info(
                                                    f"TP1 AUTO: Scaled out 50% of "
                                                    f"{pos.position_id}"
                                                )

                                            # 2. Move stop to breakeven
                                            if execution_engine.move_stop_to_breakeven(
                                                pos
                                            ):
                                                logger.info(
                                                    f"TP1 AUTO: Stop -> breakeven for "
                                                    f"{pos.position_id}"
                                                )

                                    # TP2: Scale out 50% of remaining + move stop to TP1
                                    elif exited.status == SignalStatus.TP2_HIT:
                                        # Idempotency: Skip if already scaled beyond TP1
                                        # TP1 scales 50%, TP2 scales another 25% (50% of remaining)
                                        original = pos.original_qty or pos.qty
                                        if pos.scaled_out_qty > original * 0.5:
                                            logger.debug(
                                                f"TP2 already processed for {pos.position_id}, "
                                                f"scaled_out_qty={pos.scaled_out_qty}"
                                            )
                                        else:
                                            # 1. Scale out 50% of remaining (25% of original)
                                            if execution_engine.scale_out_position(
                                                pos, 0.5
                                            ):
                                                logger.info(
                                                    f"TP2 AUTO: Scaled out 50% remaining "
                                                    f"of {pos.position_id}"
                                                )

                                            # 2. Move stop to TP1 level
                                            tp1_level = exited.take_profit_1
                                            if tp1_level:
                                                if execution_engine.modify_stop_loss(
                                                    pos, tp1_level
                                                ):
                                                    logger.info(
                                                        f"TP2 AUTO: Stop -> TP1 level "
                                                        f"${tp1_level:.2f} for "
                                                        f"{pos.position_id}"
                                                    )
                                            else:
                                                logger.warning(
                                                    f"TP2 AUTO: Cannot move stop to TP1 - "
                                                    f"take_profit_1 not set for {exited.signal_id}"
                                                )

                                    # TP3: Close runner position (trailing stop hit)
                                    elif exited.status == SignalStatus.TP3_HIT:
                                        if execution_engine.close_position_emergency(pos):
                                            pos.status = TradeStatus.CLOSED
                                            logger.info(
                                                f"TP3 AUTO: Runner closed for "
                                                f"{pos.position_id}"
                                            )

                                    # INVALIDATED: Emergency close position
                                    elif exited.status == SignalStatus.INVALIDATED:
                                        if execution_engine.close_position_emergency(pos):
                                            pos.status = TradeStatus.CLOSED
                                            logger.info(
                                                f"INVALIDATED: Emergency closed "
                                                f"{pos.position_id}"
                                            )

                                    # Persist position updates
                                    position_repo.update_position(pos)

                            # Remove exited signals from expiration checking
                            if exited in active_signals:
                                active_signals.remove(exited)

                        # 2. Expiration Check on REMAINING Waiting signals
                        for sig in active_signals:
                            # Only expire WAITING signals.
                            # If TP1_HIT, it's active.
                            if sig.status != SignalStatus.WAITING:
                                continue

                            cutoff_date = sig.ds + timedelta(days=1)
                            if today_date > cutoff_date:
                                logger.info(
                                    f"EXPIRING Signal {sig.signal_id} (Date: {sig.ds})",
                                    extra={"symbol": symbol, "signal_id": sig.signal_id},
                                )
                                sig.status = SignalStatus.EXPIRED
                                sig.exit_reason = ExitReason.EXPIRED
                                repo.update_signal(sig)
                                # Reply in thread if available, fallback to main channel
                                discord.send_message(
                                    f"⏳ **SIGNAL EXPIRED: {symbol}** ⏳\n"
                                    f"Signal from {sig.ds} expired (24h Limit).",
                                    thread_id=sig.discord_thread_id,
                                    asset_class=asset_class,
                                )

                except Exception as e:
                    errors_encountered += 1
                    symbol_duration = time.time() - symbol_start_time
                    metrics.record_failure("signal_generation", symbol_duration)
                    logger.error(
                        f"Error processing {symbol} ({asset_class.value}): {e}",
                        exc_info=True,
                        extra={"symbol": symbol, "asset_class": asset_class.value},
                    )
                    # Continue to next symbol despite error
                    continue
                finally:
                    # Advance progress bar after each symbol
                    progress.advance(task)

        # =========================================================================
        # POSITION SYNC LOOP
        # Synchronize open positions with Alpaca broker state.
        # This updates TP/SL leg IDs and detects externally closed positions.
        # =========================================================================
        if settings.ENABLE_EXECUTION:
            logger.info("Syncing open positions with Alpaca...")
            sync_start = time.time()
            try:
                open_positions = position_repo.get_open_positions()
                synced_count = 0
                closed_count = 0

                for pos in open_positions:
                    if shutdown_requested:
                        logger.info("Shutdown requested. Stopping position sync...")
                        break

                    try:
                        original_status = pos.status
                        updated_pos = execution_engine.sync_position_status(pos)

                        # Check if position was closed externally (TP/SL hit)
                        if updated_pos.status != original_status:
                            position_repo.update_position(updated_pos)
                            closed_count += 1
                            logger.info(
                                f"Position {updated_pos.position_id} closed: "
                                f"{updated_pos.status.value}",
                                extra={
                                    "position_id": updated_pos.position_id,
                                    "symbol": updated_pos.symbol,
                                    "status": updated_pos.status.value,
                                },
                            )

                            # Send trade close notification with PnL
                            if (
                                updated_pos.status == TradeStatus.CLOSED
                                and updated_pos.exit_fill_price
                            ):
                                # Fetch associated signal for thread_id
                                signal_for_pos = repo.get_by_id(updated_pos.signal_id)
                                if signal_for_pos:
                                    # Calculate PnL including scaled-out portions
                                    entry = updated_pos.entry_fill_price
                                    exit_price = updated_pos.exit_fill_price
                                    is_long = updated_pos.side == OrderSide.BUY

                                    # PnL from scaled-out portions (TP1, TP2)
                                    scaled_pnl = 0.0
                                    for scale in updated_pos.scaled_out_prices:
                                        scale_qty = scale.get("qty", 0)
                                        scale_price = scale.get("price", entry)
                                        if is_long:
                                            scaled_pnl += (
                                                scale_price - entry
                                            ) * scale_qty
                                        else:
                                            scaled_pnl += (
                                                entry - scale_price
                                            ) * scale_qty

                                    # PnL from final exit (remaining qty)
                                    remaining_qty = updated_pos.qty
                                    if is_long:
                                        final_pnl = (exit_price - entry) * remaining_qty
                                    else:
                                        final_pnl = (entry - exit_price) * remaining_qty

                                    # Total PnL
                                    pnl_usd = scaled_pnl + final_pnl
                                    total_qty = updated_pos.original_qty or (
                                        remaining_qty + updated_pos.scaled_out_qty
                                    )
                                    pnl_pct = (pnl_usd / (entry * total_qty)) * 100

                                    # Calculate duration
                                    duration_str = "N/A"
                                    if updated_pos.filled_at and updated_pos.exit_time:
                                        duration = (
                                            updated_pos.exit_time - updated_pos.filled_at
                                        )
                                        hours, remainder = divmod(
                                            duration.total_seconds(), 3600
                                        )
                                        minutes = remainder // 60
                                        duration_str = f"{int(hours)}h {int(minutes)}m"

                                    # Determine exit reason based on PnL
                                    exit_reason = (
                                        "Take Profit" if pnl_usd >= 0 else "Stop Loss"
                                    )

                                    discord.send_trade_close(
                                        signal=signal_for_pos,
                                        position=updated_pos,
                                        pnl_usd=pnl_usd,
                                        pnl_pct=pnl_pct,
                                        duration_str=duration_str,
                                        exit_reason=exit_reason,
                                    )
                        elif updated_pos != pos:
                            # Any field changed (leg IDs, filled_at, entry_fill_price, etc.)
                            position_repo.update_position(updated_pos)
                            synced_count += 1

                            # Log what changed for debugging
                            changes = []
                            if updated_pos.tp_order_id != pos.tp_order_id:
                                changes.append(f"TP={updated_pos.tp_order_id}")
                            if updated_pos.sl_order_id != pos.sl_order_id:
                                changes.append(f"SL={updated_pos.sl_order_id}")
                            if updated_pos.filled_at != pos.filled_at:
                                changes.append(f"filled_at={updated_pos.filled_at}")
                            if updated_pos.entry_fill_price != pos.entry_fill_price:
                                changes.append(
                                    f"entry_fill_price={updated_pos.entry_fill_price}"
                                )
                            if updated_pos.failed_reason != pos.failed_reason:
                                changes.append(
                                    f"failed_reason={updated_pos.failed_reason}"
                                )

                            logger.info(
                                f"Position {updated_pos.position_id} synced: "
                                f"{', '.join(changes) if changes else 'fields updated'}",
                                extra={
                                    "position_id": updated_pos.position_id,
                                    "symbol": updated_pos.symbol,
                                },
                            )

                    except Exception as e:
                        logger.warning(
                            f"Failed to sync position {pos.position_id}: {e}",
                            extra={"position_id": pos.position_id},
                        )

                sync_duration = time.time() - sync_start
                logger.info(
                    f"Position sync complete: {synced_count} updated, "
                    f"{closed_count} closed",
                    extra={
                        "synced": synced_count,
                        "closed": closed_count,
                        "duration_seconds": round(sync_duration, 3),
                    },
                )
            except Exception as e:
                logger.error(f"Position sync failed: {e}", exc_info=True)

        # Display Rich execution summary table
        total_duration = time.time() - app_start_time
        console.print()  # Empty line for spacing
        summary_table = create_execution_summary_table(
            total_duration=total_duration,
            symbols_processed=symbols_processed,
            total_symbols=len(portfolio_items),
            signals_found=signals_found,
            errors_encountered=errors_encountered,
        )
        console.print(summary_table)
        console.print()  # Empty line for spacing

        # Log detailed metrics (also uses Rich table now)
        metrics.log_summary(logger)

        if shutdown_requested:
            logger.info("Signal generation cycle interrupted by shutdown request.")
        else:
            logger.info("Signal generation cycle complete.")

    except Exception as e:
        logger.critical(f"Fatal error in main application loop: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
