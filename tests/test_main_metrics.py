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
        stack.enter_context(patch("crypto_signals.main.SignalGenerator"))
        stack.enter_context(patch("crypto_signals.main.SignalRepository"))
        stack.enter_context(patch("crypto_signals.main.MarketDataProvider"))
        stack.enter_context(patch("crypto_signals.main.DiscordClient"))
        stack.enter_context(patch("crypto_signals.main.init_secrets", return_value=True))
        stack.enter_context(patch("crypto_signals.main.JobLockRepository"))
        stack.enter_context(patch("crypto_signals.main.AssetValidationService"))
        stack.enter_context(patch("crypto_signals.main.StateReconciler"))
        stack.enter_context(patch("crypto_signals.main.TradeArchivalPipeline"))
        stack.enter_context(patch("crypto_signals.main.FeePatchPipeline"))
        stack.enter_context(patch("crypto_signals.main.PricePatchPipeline"))
        stack.enter_context(patch("crypto_signals.main.JobMetadataRepository"))
        stack.enter_context(patch("crypto_signals.main.get_stock_data_client"))
        stack.enter_context(patch("crypto_signals.main.get_crypto_data_client"))
        stack.enter_context(patch("crypto_signals.main.get_trading_client"))
        stack.enter_context(patch("crypto_signals.main.AccountSnapshotPipeline"))
        stack.enter_context(patch("crypto_signals.main.StrategySyncPipeline"))

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

        # Configure Job Lock
        # (Already mocked in context manager, but ensure acquire returns True)

        yield {
            "metrics": mock_metrics,
            "pos_repo": mock_pos_repo,
            "exec_engine": mock_exec_engine,
        }


def test_position_sync_metrics_failure_individual(mock_deps_metrics):
    """Test that individual position sync failure records a metric."""
    mocks = mock_deps_metrics

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

    # Make get_open_positions raise exception (global failure)
    mocks["pos_repo"].return_value.get_open_positions.side_effect = RuntimeError(
        "DB Error"
    )

    # Run main
    main(smoke_test=False)

    # Verify record_failure called for global sync
    # We expect a call like record_failure("position_sync", time_duration)
    # Since time_duration is variable, we check call args

    calls = mocks["metrics"].record_failure.call_args_list
    assert any(call.args[0] == "position_sync" for call in calls)
