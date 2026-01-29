from unittest.mock import MagicMock, patch

import pytest
from crypto_signals.main import main


@pytest.fixture
def mock_deps_metrics():
    """Mock dependencies for metric testing."""
    with (
        patch("crypto_signals.main.get_metrics_collector") as mock_get_metrics,
        patch("crypto_signals.main.get_settings") as mock_settings,
        patch("crypto_signals.main.PositionRepository") as mock_pos_repo,
        patch("crypto_signals.main.ExecutionEngine") as mock_exec_engine,
        patch("crypto_signals.main.SignalGenerator"),
        patch("crypto_signals.main.SignalRepository"),
        patch("crypto_signals.main.MarketDataProvider"),
        patch("crypto_signals.main.DiscordClient"),
        patch("crypto_signals.main.init_secrets", return_value=True),
        patch("crypto_signals.main.JobLockRepository"),
        patch("crypto_signals.main.AssetValidationService"),
        patch("crypto_signals.main.StateReconciler"),
        patch("crypto_signals.main.TradeArchivalPipeline"),
        patch("crypto_signals.main.FeePatchPipeline"),
        patch("crypto_signals.main.PricePatchPipeline"),
        patch("crypto_signals.main.JobMetadataRepository"),
        patch("crypto_signals.main.get_stock_data_client"),
        patch("crypto_signals.main.get_crypto_data_client"),
        patch("crypto_signals.main.get_trading_client"),
    ):
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
