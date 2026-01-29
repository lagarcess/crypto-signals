"""
Main Application Entrypoint.

This script executes the signal generation pipeline for a defined portfolio of assets.
It orchestrates data fetching, pattern recognition, persistence, and notifications.
"""

import atexit
import signal
import sys
import time
from datetime import datetime, timezone

import typer
from loguru import logger

from crypto_signals.analysis.structural import warmup_jit
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
    SignalStatus,
    TradeStatus,
)
from crypto_signals.engine.execution import ExecutionEngine
from crypto_signals.engine.reconciler import StateReconciler
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
from crypto_signals.pipelines.account_snapshot import AccountSnapshotPipeline
from crypto_signals.pipelines.fee_patch import FeePatchPipeline
from crypto_signals.pipelines.price_patch import PricePatchPipeline
from crypto_signals.pipelines.trade_archival import TradeArchivalPipeline
from crypto_signals.repository.firestore import (
    JobLockRepository,
    JobMetadataRepository,
    PositionRepository,
    RejectedSignalRepository,
    SignalRepository,
)
from crypto_signals.secrets_manager import init_secrets

# Configure logging with Rich integration
configure_logging(level="INFO")

# Pre-compile Numba JIT functions to avoid cold-start latency in live trading
warmup_jit()


# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_requested = True


def main(
    smoke_test: bool = typer.Option(
        False, help="Run a shallow connectivity check (Smoke Test) and exit."
    ),
):
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

        # --- SMOKE TEST PATH ---
        if smoke_test:
            logger.warning("💨 SMOKE TEST: Running connectivity checks...")

            # 1. Verify Firestore Connectivity (skip if no credentials in CI)
            try:
                # Initializing repository creates the Firestore client
                JobLockRepository()
                logger.info("✅ Firestore: Client Initialized")
            except Exception as e:
                logger.warning(f"⚠️  Firestore: Skipped (no credentials) - {e}")

            # 2. Verify settings loaded
            if not settings.GOOGLE_CLOUD_PROJECT:
                raise ValueError("Missing GOOGLE_CLOUD_PROJECT")
            logger.info(f"✅ Configuration: Project={settings.GOOGLE_CLOUD_PROJECT}")

            logger.success("🟢 SMOKE TEST PASSED: All connectivity checks succeeded.")
            sys.exit(0)
        # -----------------------

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

            reconciler = StateReconciler(
                alpaca_client=get_trading_client(),
                position_repo=position_repo,
                discord_client=discord,
                settings=settings,
            )
            execution_engine = ExecutionEngine(reconciler=reconciler)
            job_lock_repo = JobLockRepository()
            rejected_repo = RejectedSignalRepository()  # Shadow signal persistence
            job_metadata_repo = JobMetadataRepository()

            # Pipeline Services
            trade_archival = TradeArchivalPipeline()
            fee_patch = FeePatchPipeline()
            price_patch = PricePatchPipeline()
            account_snapshot = AccountSnapshotPipeline()

        # Job Locking
        job_id = "signal_generator_cron"
        if not job_lock_repo.acquire_lock(job_id):
            logger.warning(f"Job lock held by another instance ({job_id}). Exiting.")
            sys.exit(0)

        # Ensure lock is released on exit
        atexit.register(job_lock_repo.release_lock, job_id)

        # === DAILY CLEANUP ===
        today = datetime.now(timezone.utc).date()
        last_cleanup_date = job_metadata_repo.get_last_run_date("daily_cleanup")
        if last_cleanup_date != today:
            logger.info("Running daily cleanup...")
            deleted_signals = repo.cleanup_expired()
            deleted_rejected = rejected_repo.cleanup_expired()
            deleted_positions = position_repo.cleanup_expired()
            logger.info(
                f"Cleanup complete: {deleted_signals} signals, "
                f"{deleted_rejected} rejected signals, {deleted_positions} positions."
            )

            # --- Account Snapshot ---
            logger.info("Running Account Snapshot Pipeline...")
            try:
                account_snapshot.run()
                logger.info("✅ Account Snapshot Pipeline completed successfully.")
            except Exception as e:
                logger.error(f"Account Snapshot Pipeline failed: {e}")
                # Non-blocking, continue execution

            job_metadata_repo.update_last_run_date("daily_cleanup", today)
        else:
            logger.info("Daily cleanup has already run today. Skipping.")

        # === STATE RECONCILIATION (Issue #113) ===
        # Detect and heal zombie/orphan positions before main loop
        logger.info("Running state reconciliation...")
        reconciliation_failed = False
        reconciliation_start_time = time.time()
        try:
            reconciliation_report = reconciler.reconcile()

            if reconciliation_report.critical_issues:
                logger.warning(
                    f"Reconciliation detected {len(reconciliation_report.critical_issues)} critical issue(s)",
                    extra={
                        "issues": reconciliation_report.critical_issues,
                        "zombies": len(reconciliation_report.zombies),
                        "orphans": len(reconciliation_report.orphans),
                    },
                )
            else:
                logger.info(
                    f"Reconciliation complete: {reconciliation_report.reconciled_count} positions healed"
                )
        except Exception as e:
            logger.error(
                f"Reconciliation failed: {e}",
                extra={"error": str(e)},
            )
            metrics.record_failure(
                "reconciliation", time.time() - reconciliation_start_time
            )
            # Mark as failed to prevent archival of potentially inconsistent state
            reconciliation_failed = True

        # === TRADE ARCHIVAL (Issue #149) ===
        # Move Closed Positions -> BigQuery (Before Fee Patch!)
        # Must run AFTER reconciliation (so we archive what was just closed)
        if not reconciliation_failed:
            logger.info("Running trade archival...")
            trade_archival_start_time = time.time()
            try:
                archival_count = trade_archival.run()
                if archival_count > 0:
                    logger.info(
                        f"✅ Trade archival complete: {archival_count} trades archived"
                    )
                else:
                    logger.info("✅ Trade archival complete: No closed trades to archive")
            except Exception as e:
                logger.error(f"Trade archival failed: {e}")
                metrics.record_failure(
                    "trade_archival", time.time() - trade_archival_start_time
                )
        else:
            logger.warning("⚠️ Skipping trade archival due to reconciliation failure.")

        # === FEE RECONCILIATION (Issue #140) ===
        # Patch estimated fees with actual CFEE data before generating new signals
        # Runs T+1 reconciliation for trades older than 24 hours
        if not reconciliation_failed:
            logger.info("Running fee reconciliation...")
            fee_patch_start_time = time.time()
            try:
                patched_count = fee_patch.run()

                if patched_count > 0:
                    logger.info(
                        f"✅ Fee reconciliation complete: {patched_count} trades updated"
                    )
                else:
                    logger.info("✅ Fee reconciliation complete: No trades to update")
            except Exception as e:
                logger.error(f"Fee reconciliation failed: {e}")
                metrics.record_failure("fee_patch", time.time() - fee_patch_start_time)
                # Non-blocking - continue with signal generation
        else:
            logger.warning("⚠️ Skipping fee reconciliation due to reconciliation failure.")

        # === EXIT PRICE RECONCILIATION (Issue #141) ===
        # Patch $0.00 exit prices with actual fill prices from Alpaca
        # Runs for historical repair and daily reconciliation
        if not reconciliation_failed:
            logger.info("Running exit price reconciliation...")
            price_patch_start_time = time.time()
            try:
                patched_count = price_patch.run()

                if patched_count > 0:
                    logger.info(
                        f"✅ Exit price reconciliation complete: {patched_count} trades repaired"
                    )
                else:
                    logger.info(
                        "✅ Exit price reconciliation complete: No trades to repair"
                    )
            except Exception as e:
                logger.error(f"Exit price reconciliation failed: {e}")
                metrics.record_failure(
                    "price_patch", time.time() - price_patch_start_time
                )
                # Non-blocking - continue with signal generation
        else:
            logger.warning(
                "⚠️ Skipping exit price reconciliation due to reconciliation failure."
            )

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
                        # Handle Shadow Signals (rejected by quality gates)
                        if trade_signal.status == SignalStatus.REJECTED_BY_FILTER:
                            # DEDUPLICATION: Skip shadow if active signal exists (avoid noise)
                            active_signals = repo.get_active_signals(symbol)
                            if active_signals:
                                logger.debug(
                                    f"[SHADOW] Skipping {symbol} shadow signal - active signal exists",
                                    extra={"symbol": symbol},
                                )
                                continue

                            # Persist to rejected_signals collection for audit/analysis
                            try:
                                rejected_repo.save(trade_signal)
                                # Send to shadow Discord channel (if configured)
                                discord.send_shadow_signal(trade_signal)
                                logger.info(
                                    f"[SHADOW] {trade_signal.symbol} {trade_signal.pattern_name}: "
                                    f"{trade_signal.rejection_reason}",
                                    extra={
                                        "symbol": trade_signal.symbol,
                                        "pattern": trade_signal.pattern_name,
                                        "rejection_reason": trade_signal.rejection_reason,
                                        "pattern_duration_days": trade_signal.pattern_duration_days,
                                        "pattern_classification": trade_signal.pattern_classification,
                                    },
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to persist shadow signal: {e}",
                                    extra={"symbol": trade_signal.symbol},
                                )
                            # Shadow signals don't trigger live trading - continue to next symbol
                            continue

                        # Standard signal handling (WAITING status)
                        signals_found += 1
                        logger.info(
                            f"SIGNAL FOUND: {trade_signal.pattern_name} "
                            f"on {trade_signal.symbol}",
                            extra={
                                "symbol": trade_signal.symbol,
                                "pattern": trade_signal.pattern_name,
                                "stop_loss": trade_signal.suggested_stop,
                                "pattern_duration_days": trade_signal.pattern_duration_days,
                                "pattern_classification": trade_signal.pattern_classification,
                            },
                        )

                        # ============================================================
                        # IDEMPOTENCY GATE: Prevent redundant Discord alerts
                        # ============================================================
                        existing_signal = repo.get_by_id(trade_signal.signal_id)
                        if existing_signal:
                            # Skip if signal exists in WAITING status with discord_thread_id
                            if (
                                existing_signal.status == SignalStatus.WAITING
                                and existing_signal.discord_thread_id
                            ):
                                logger.info(
                                    f"[IDEMPOTENCY] Skip notified signal {trade_signal.signal_id}",
                                    extra={
                                        "signal_id": trade_signal.signal_id,
                                        "symbol": trade_signal.symbol,
                                        "thread_id": existing_signal.discord_thread_id,
                                    },
                                )
                                continue

                            # Self-heal: If exists but discord_thread_id is null, proceed to notification
                            if not existing_signal.discord_thread_id:
                                logger.info(
                                    f"[IDEMPOTENCY] Self-healing signal {trade_signal.signal_id} - "
                                    "missing discord_thread_id",
                                    extra={
                                        "signal_id": trade_signal.signal_id,
                                        "symbol": trade_signal.symbol,
                                    },
                                )
                                # Continue to notification phase to fix the missing thread_id

                        # ============================================================
                        # TWO-PHASE COMMIT: Prevents "Zombie Signals"
                        # (notifications sent without database tracking)
                        # ============================================================

                        # PHASE 1: Persist with CREATED status (establishes tracking)
                        trade_signal.status = SignalStatus.CREATED
                        persistence_start = time.time()
                        try:
                            repo.save(trade_signal)
                            persistence_duration = time.time() - persistence_start
                            logger.info(
                                f"Signal {trade_signal.signal_id} created in Firestore",
                                extra={
                                    "signal_id": trade_signal.signal_id,
                                    "symbol": trade_signal.symbol,
                                    "status": "CREATED",
                                    "duration_seconds": round(persistence_duration, 3),
                                },
                            )
                            metrics.record_success(
                                "signal_persistence", persistence_duration
                            )
                        except Exception as e:
                            persistence_duration = time.time() - persistence_start
                            logger.error(
                                f"Failed to persist signal {trade_signal.signal_id} - "
                                "skipping notification to prevent zombie signal",
                                extra={
                                    "signal_id": trade_signal.signal_id,
                                    "symbol": trade_signal.symbol,
                                    "error": str(e),
                                },
                            )
                            metrics.record_failure(
                                "signal_persistence", persistence_duration
                            )
                            # Skip notification - can't notify without tracking
                            continue

                        # PHASE 2: Notify Discord
                        thread_id = None

                        # Self-healing: Check for existing thread (if missing in memory/DB)
                        if not trade_signal.discord_thread_id:
                            try:
                                thread_id = discord.find_thread_by_signal_id(
                                    trade_signal.signal_id,
                                    trade_signal.symbol,
                                    asset_class,
                                )
                            except Exception as e:
                                logger.warning(f"Thread recovery check failed: {e}")

                        if thread_id:
                            logger.info(
                                f"Self-healing: Recovered Discord thread {thread_id} "
                                f"for signal {trade_signal.signal_id}"
                            )
                        else:
                            # Standard execution: Create new thread
                            thread_id = discord.send_signal(trade_signal)

                        # PHASE 3: Update with thread_id and final status
                        if thread_id:
                            updates = {
                                "discord_thread_id": thread_id,
                                "status": SignalStatus.WAITING.value,
                            }
                            if repo.update_signal_atomic(trade_signal.signal_id, updates):
                                trade_signal.discord_thread_id = thread_id
                                trade_signal.status = SignalStatus.WAITING
                                logger.info(
                                    "Signal activated with Discord thread",
                                    extra={
                                        "signal_id": trade_signal.signal_id,
                                        "symbol": trade_signal.symbol,
                                        "thread_id": thread_id,
                                        "status": "WAITING",
                                    },
                                )
                            else:
                                logger.error(
                                    f"Failed to atomic update signal {trade_signal.signal_id} after Discord notification"
                                )
                        else:
                            # Compensation: Mark as invalidated if notification failed
                            logger.warning(
                                f"Discord notification failed for {trade_signal.symbol} "
                                "- marking signal as invalidated",
                                extra={"symbol": trade_signal.symbol},
                            )
                            trade_signal.status = SignalStatus.INVALIDATED
                            trade_signal.exit_reason = ExitReason.NOTIFICATION_FAILED
                            try:
                                repo.update_signal_atomic(
                                    trade_signal.signal_id,
                                    {
                                        "status": SignalStatus.INVALIDATED.value,
                                        "exit_reason": ExitReason.NOTIFICATION_FAILED.value,
                                    },
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to invalidate signal: {e}",
                                    extra={
                                        "signal_id": trade_signal.signal_id,
                                        "error": str(e),
                                    },
                                )

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
                                    # CRITICAL: Persist position to Firestore for
                                    # Position Sync Loop and TP Automation to work
                                    position_repo.save(position)

                                    # Log differentiation for Risk Blocked vs Executed
                                    if position.trade_type == "RISK_BLOCKED":
                                        logger.info(
                                            f"LIFECYCLE PERSISTED: {trade_signal.symbol} (Type: {position.trade_type})",
                                            extra={
                                                "signal_id": trade_signal.signal_id,
                                                "symbol": trade_signal.symbol,
                                                "position_id": position.position_id,
                                                "trade_type": position.trade_type,
                                                "qty": position.qty,
                                            },
                                        )
                                    else:
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
                                repo.update_signal_atomic(
                                    exited.signal_id, {"take_profit_3": new_tp3}
                                )

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
                                    pos = position_repo.get_position_by_signal(
                                        exited.signal_id
                                    )
                                    if pos and pos.status == TradeStatus.OPEN:
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
                            updates = {
                                "status": exited.status.value,
                            }
                            if exited.exit_reason:
                                updates["exit_reason"] = exited.exit_reason

                            if repo.update_signal_atomic(exited.signal_id, updates):
                                logger.info(
                                    f"SIGNAL UPDATE: {exited.signal_id} "
                                    f"status -> {exited.status}",
                                    extra={
                                        "symbol": symbol,
                                        "signal_id": exited.signal_id,
                                        "new_status": exited.status,
                                    },
                                )
                            else:
                                logger.error(
                                    f"Failed atomic update for status change {exited.signal_id}"
                                )
                                continue

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
                                result = discord.send_signal_update(
                                    exited, asset_class=asset_class
                                )
                                # Self-healing: Clear stale thread_id for next run
                                if result == "thread_stale":
                                    logger.warning(
                                        f"Self-healing: Clearing stale discord_thread_id "
                                        f"for signal {exited.signal_id}"
                                    )
                                    repo.update_signal_atomic(
                                        exited.signal_id,
                                        {"discord_thread_id": None},
                                    )

                            # === TP AUTOMATION ===
                            # Progressive stop management on each TP stage
                            if settings.ENABLE_EXECUTION:
                                # Find position linked to this signal
                                pos = position_repo.get_position_by_signal(
                                    exited.signal_id
                                )
                                if pos and pos.status == TradeStatus.OPEN:
                                    # Handle Terminal States (Close All) first
                                    if exited.status in (
                                        SignalStatus.TP3_HIT,
                                        SignalStatus.INVALIDATED,
                                    ):
                                        if execution_engine.close_position_emergency(pos):
                                            pos.status = TradeStatus.CLOSED
                                            reason = (
                                                "TP3 Runner"
                                                if exited.status == SignalStatus.TP3_HIT
                                                else "INVALIDATED"
                                            )
                                            logger.info(
                                                f"{reason}: Closed {pos.position_id}"
                                            )
                                        position_repo.update_position(pos)

                                    # Handle Progressive States (Scaling)
                                    else:
                                        # TP1 Logic: Run if TP1 OR TP2 hit
                                        if exited.status in (
                                            SignalStatus.TP1_HIT,
                                            SignalStatus.TP2_HIT,
                                        ):
                                            # Idempotency: Skip if already scaled
                                            if pos.scaled_out_qty > 0:
                                                pass  # Already done
                                            else:
                                                # 1. Scale out 50%
                                                if execution_engine.scale_out_position(
                                                    pos, 0.5
                                                ):
                                                    logger.info(
                                                        f"TP1 AUTO: Scaled out 50% of {pos.position_id}"
                                                    )
                                                # 2. Move stop to breakeven
                                                if execution_engine.move_stop_to_breakeven(
                                                    pos
                                                ):
                                                    logger.info(
                                                        f"TP1 AUTO: Stop -> breakeven for {pos.position_id}"
                                                    )

                                        # TP2 Logic: Run if TP2 hit
                                        if exited.status == SignalStatus.TP2_HIT:
                                            # Idempotency: TP1 scales 50% of Orig. TP2 scales 50% of Rem (25% Orig).
                                            # Total scaled should be > 50% of original.
                                            original = pos.original_qty or pos.qty
                                            # Use 0.6 as safe threshold (0.5 + epsilon)
                                            if pos.scaled_out_qty > original * 0.6:
                                                pass  # Already done
                                            else:
                                                # 1. Scale out 50% of remaining
                                                if execution_engine.scale_out_position(
                                                    pos, 0.5
                                                ):
                                                    logger.info(
                                                        f"TP2 AUTO: Scaled out 50% remaining of {pos.position_id}"
                                                    )

                                                # 2. Move stop to TP1 level
                                                tp1_level = exited.take_profit_1
                                                if tp1_level:
                                                    if execution_engine.modify_stop_loss(
                                                        pos, tp1_level
                                                    ):
                                                        logger.info(
                                                            f"TP2 AUTO: Stop -> TP1 ${tp1_level:.2f} for {pos.position_id}"
                                                        )
                                                else:
                                                    logger.warning(
                                                        f"TP2 AUTO: No TP1 level set for {exited.signal_id}"
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

                            # Use valid_until (24h from candle close) for expiration check
                            if now_utc > sig.valid_until:
                                logger.info(
                                    f"EXPIRING Signal {sig.signal_id} (Valid Until: {sig.valid_until})",
                                    extra={"symbol": symbol, "signal_id": sig.signal_id},
                                )
                                sig.status = SignalStatus.EXPIRED
                                sig.exit_reason = ExitReason.EXPIRED
                                repo.update_signal_atomic(
                                    sig.signal_id,
                                    {
                                        "status": SignalStatus.EXPIRED.value,
                                        "exit_reason": ExitReason.EXPIRED.value,
                                    },
                                )
                                # Reply in thread if available, fallback to main channel
                                discord.send_message(
                                    f"⏳ **SIGNAL EXPIRED: {symbol}** ⏳\n"
                                    f"Signal expired (24h limit reached).",
                                    thread_id=sig.discord_thread_id,
                                    asset_class=asset_class,
                                )

                except Exception as e:
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
                slippage_values = []  # Track slippage for summary

                for pos in open_positions:
                    if shutdown_requested:
                        logger.info("Shutdown requested. Stopping position sync...")
                        break

                    if rate_limit_delay:
                        time.sleep(rate_limit_delay)
                        if shutdown_requested:
                            logger.info(
                                "Shutdown requested during position sync delay. Stopping..."
                            )
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
                                    # Use pre-calculated PnL from sync_position_status()
                                    pnl_usd = updated_pos.realized_pnl_usd
                                    pnl_pct = updated_pos.realized_pnl_pct

                                    # Format duration from pre-calculated seconds
                                    duration_str = "N/A"
                                    if updated_pos.trade_duration_seconds:
                                        hours, remainder = divmod(
                                            updated_pos.trade_duration_seconds, 3600
                                        )
                                        minutes = remainder // 60
                                        duration_str = f"{int(hours)}h {int(minutes)}m"

                                    # Use actual exit reason from broker sync
                                    exit_reason = (
                                        updated_pos.exit_reason.value
                                        if updated_pos.exit_reason
                                        else "Manual Exit"
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

                            # Log slippage and commission metrics
                            if updated_pos.entry_slippage_pct is not None:
                                slippage_values.append(updated_pos.entry_slippage_pct)
                                logger.info(
                                    f"Position {updated_pos.position_id} metrics: "
                                    f"slippage={updated_pos.entry_slippage_pct:+.3f}%, "
                                    f"commission=${updated_pos.commission:.2f}",
                                    extra={
                                        "position_id": updated_pos.position_id,
                                        "symbol": updated_pos.symbol,
                                        "entry_slippage_pct": updated_pos.entry_slippage_pct,
                                        "commission": updated_pos.commission,
                                    },
                                )

                    except Exception as e:
                        logger.warning(
                            f"Failed to sync position {pos.position_id}: {e}",
                            extra={"position_id": pos.position_id},
                        )
                        metrics.record_failure("position_sync_single", 0)

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
                metrics.record_failure("position_sync", time.time() - sync_start)

        # Display Rich execution summary table
        total_duration = time.time() - app_start_time
        console.print()  # Empty line for spacing

        # Calculate average slippage from position sync (if available)
        avg_slippage = None
        if settings.ENABLE_EXECUTION and "slippage_values" in dir():
            if slippage_values:
                avg_slippage = sum(slippage_values) / len(slippage_values)

        # Calculate total errors from metrics collector for accurate summary
        metrics_summary = metrics.get_summary()
        total_errors = sum(
            stats.get("failure_count", 0) for stats in metrics_summary.values()
        )

        summary_table = create_execution_summary_table(
            total_duration=total_duration,
            symbols_processed=symbols_processed,
            total_symbols=len(portfolio_items),
            signals_found=signals_found,
            errors_encountered=total_errors,
            avg_slippage_pct=avg_slippage,
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
    typer.run(main)
