from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.main import main


@pytest.fixture
def mock_deps_metrics():
    """Mock dependencies for metric testing."""
    with ExitStack() as stack:
        mock_get_metrics = stack.enter_context(
            patch("crypto_signals.main.get_metrics_collector")
        )
        mock_settings = stack.enter_context(patch("crypto_signals.main.get_settings"))
        mock_pos_repo = stack.enter_context(
            patch("crypto_signals.main.PositionRepository")
        )
        mock_exec_engine = stack.enter_context(
            patch("crypto_signals.main.ExecutionEngine")
        )
        generator_mock = stack.enter_context(patch("crypto_signals.main.SignalGenerator"))
        stack.enter_context(patch("crypto_signals.main.SignalRepository"))
        stack.enter_context(patch("crypto_signals.main.RejectedSignalRepository"))
        stack.enter_context(patch("crypto_signals.main.MarketDataProvider"))
        stack.enter_context(patch("crypto_signals.main.DiscordClient"))
        stack.enter_context(patch("crypto_signals.main.init_secrets", return_value=True))
        stack.enter_context(
            patch("crypto_signals.main.load_config_from_firestore", return_value={})
        )
        stack.enter_context(patch("crypto_signals.main.JobLockRepository"))
        stack.enter_context(patch("crypto_signals.main.AssetValidationService"))
        stack.enter_context(patch("crypto_signals.main.StateReconciler"))
        trade_archive = stack.enter_context(
            patch("crypto_signals.main.TradeArchivalPipeline")
        )
        fee_patch = stack.enter_context(patch("crypto_signals.main.FeePatchPipeline"))
        price_patch = stack.enter_context(patch("crypto_signals.main.PricePatchPipeline"))
        stack.enter_context(patch("crypto_signals.main.JobMetadataRepository"))
        stack.enter_context(patch("crypto_signals.main.get_stock_data_client"))
        stack.enter_context(patch("crypto_signals.main.get_crypto_data_client"))
        stack.enter_context(patch("crypto_signals.main.get_trading_client"))
        account_snap = stack.enter_context(
            patch("crypto_signals.main.AccountSnapshotPipeline")
        )
        strategy_sync = stack.enter_context(
            patch("crypto_signals.main.StrategySyncPipeline")
        )
        expired_archive = stack.enter_context(
            patch("crypto_signals.main.ExpiredSignalArchivalPipeline")
        )
        rejected_archive = stack.enter_context(
            patch("crypto_signals.main.RejectedSignalArchival")
        )

        # Prevent pipeline hangs
        trade_archive.return_value.run.return_value = 0
        fee_patch.return_value.run.return_value = 0
        price_patch.return_value.run.return_value = 0
        account_snap.return_value.run.return_value = 0
        strategy_sync.return_value.run.return_value = 0
        expired_archive.return_value.run.return_value = 0
        rejected_archive.return_value.run.return_value = 0

        # Configure Metrics Mock
        mock_metrics = MagicMock()
        mock_metrics.get_summary.return_value = {}
        mock_get_metrics.return_value = mock_metrics

        # Configure Settings
        mock_settings.return_value.ENABLE_EXECUTION = True
        mock_settings.return_value.ENABLE_GCP_LOGGING = False
        mock_settings.return_value.CRYPTO_SYMBOLS = ["BTC/USD"]
        mock_settings.return_value.EQUITY_SYMBOLS = []
        mock_settings.return_value.RATE_LIMIT_DELAY = 0.0
        mock_settings.return_value.MAX_WORKERS = 1

        # Configure Job Lock
        # (Already mocked in context manager, but ensure acquire returns True)

        yield {
            "metrics": mock_metrics,
            "pos_repo": mock_pos_repo,
            "exec_engine": mock_exec_engine,
            "generator": generator_mock,
        }


def test_position_sync_metrics_failure_individual(mock_deps_metrics):
    """Test that individual position sync failure records a metric."""
    mocks = mock_deps_metrics

    # Mock generator to avoid infinite loops from MagicMocks
    mocks["generator"].return_value.generate_signals.return_value = None

    # Setup open positions
    mock_pos = MagicMock()
    mock_pos.position_id = "pos-fail"
    mocks["pos_repo"].return_value.get_open_positions.return_value = [mock_pos]

    # Make sync raise exception
    mocks["exec_engine"].return_value.sync_position_status.side_effect = RuntimeError(
        "Sync Error"
    )

    # Run main
    main(smoke_test=False)

    # Verify record_failure called for individual position
    mocks["metrics"].record_failure.assert_any_call("position_sync_single", 0)


def test_position_sync_metrics_failure_global(mock_deps_metrics):
    """Test that global position sync loop failure records a metric."""
    mocks = mock_deps_metrics

    # Mock generator to avoid infinite loops from MagicMocks
    mocks["generator"].return_value.generate_signals.return_value = None

    # Since main.py now uses StateReconciler, mock that instead of pos_repo
    with patch("crypto_signals.main.StateReconciler") as mock_reconciler:
        mock_reconciler_instance = mock_reconciler.return_value
        mock_reconciler_instance.reconcile.side_effect = RuntimeError("Sync Error")

        # Run main
        main(smoke_test=False)

        # Verify record_failure called for global sync
        calls = mocks["metrics"].record_failure.call_args_list
        assert any(call.args[0] == "reconciliation" for call in calls)
