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
from crypto_signals.domain.schemas import AssetClass, ExitReason, SignalStatus
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
from crypto_signals.repository.firestore import SignalRepository
from crypto_signals.secrets_manager import init_secrets

# Configure logging with Rich integration
configure_logging(level="INFO")

# Enable GCP Cloud Logging if configured (additive - does not disable Rich output)
_settings = get_settings()
if _settings.ENABLE_GCP_LOGGING:
    setup_gcp_logging()


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
                discord = DiscordClient()
                asset_validator = AssetValidationService(get_trading_client())
                execution_engine = ExecutionEngine()

        # Define Portfolio
        settings = get_settings()
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
                            status_emoji = {
                                SignalStatus.INVALIDATED: "🚫",
                                SignalStatus.TP1_HIT: "🎯",
                                SignalStatus.TP2_HIT: "🚀",
                                SignalStatus.TP3_HIT: "🌕",
                                SignalStatus.EXPIRED: "⏳",
                            }.get(exited.status, "ℹ️")

                            msg = (
                                f"{status_emoji} **SIGNAL UPDATE: {symbol}** {status_emoji}\n"
                                f"**Status**: {exited.status.value}\n"
                                f"**Pattern**: {exited.pattern_name}\n"
                            )

                            if exited.exit_reason:
                                msg += f"**Reason**: {exited.exit_reason}\n"

                            if exited.status == SignalStatus.TP1_HIT:
                                msg += "ℹ️ **Action**: Scaling Out (50%) & Stop -> **Breakeven**"

                            # Self-healing: If thread_id is missing (orphaned signal),
                            # send recovery message to main channel instead of creating
                            # a confusing new entry thread
                            if not exited.discord_thread_id:
                                logger.info(
                                    f"Self-healing: Orphaned signal {exited.signal_id} - "
                                    "sending update to main channel"
                                )
                                # Prepend recovery notice to the message
                                recovery_msg = (
                                    f"🔄 **THREAD RECOVERY: {symbol}** 🔄\n"
                                    f"*(Original thread unavailable)*\n\n"
                                    f"{msg}"
                                )
                                discord.send_message(
                                    recovery_msg, asset_class=asset_class
                                )
                            else:
                                # Reply in thread if available
                                discord.send_message(
                                    msg,
                                    thread_id=exited.discord_thread_id,
                                    asset_class=asset_class,
                                )

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
